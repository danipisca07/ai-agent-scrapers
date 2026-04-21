# Step-Level Control: Stagehand `act()` vs browser_use

A comparison of how each library exposes fine-grained, per-step browser control, and how to approximate Stagehand's `act()` primitive in browser_use.

---

## 1. The core difference

| Aspect | Stagehand | browser_use |
|---|---|---|
| Atomic primitive | `page.act("click search")` | none — only `Agent.run()` |
| One NL instruction → one LLM call | ✅ by design | ❌ Agent wraps multi-step loop |
| Observe step | `page.observe()` returns candidate actions | `DomService.get_clickable_elements()` |
| Extract step | `page.extract(schema)` | `@controller.action` + Pydantic output model |
| Caching granularity | per `act()` call | per `Agent.run()` history (bundle) |
| Prompt size per step | minimal (just the instruction + DOM) | full Agent system prompt + memory + DOM |

Stagehand was designed around small, composable LLM calls. browser_use was designed around an autonomous agent loop. This shapes every downstream decision — especially caching.

---

## 2. What browser_use actually exposes

### 2.1 High-level: `Agent`
The default path. You hand the full task as a string; the Agent plans and executes all steps internally. This is what `browser_use/scraper.py` currently does.

```python
agent = Agent(task="Go to HN, click story 1, go back, click story 2, ...", llm=llm)
await agent.run()
```

Caching: `agent.history.save_to_file(path)` + `agent.rerun_history(history)`. All-or-nothing at the run level.

### 2.2 Mid-level: `@controller.action`
Register deterministic Python functions the Agent can call. These are **not** per-step LLM calls — they are tools the Agent chooses between.

```python
from browser_use import Controller
controller = Controller()

@controller.action("Click story by index")
async def click_story(index: int, browser):
    page = await browser.get_current_page()
    await page.click(f".athing:nth-child({index}) .titleline > a")

agent = Agent(task=..., llm=llm, controller=controller)
```

Useful for narrowing the action space, not for per-step control.

### 2.3 Low-level: `DomService` + `Browser` + `Page`
Fully manual. You drive everything.

```python
from browser_use import Browser, BrowserConfig
from browser_use.dom.service import DomService

browser = Browser(config=BrowserConfig())
async with await browser.new_context() as ctx:
    page = await ctx.get_current_page()
    await page.goto("https://news.ycombinator.com")
    dom = DomService(page)
    state = await dom.get_clickable_elements()
    # state.selector_map: {index -> element}
    # state.element_tree: serialized DOM
    await page.click(selector)
```

Closest to Playwright. No LLM involved unless you wire one in yourself.

### 2.4 Per-step Agent: `max_steps=1` + `add_new_task()`
The closest thing to Stagehand's `act()` **without** leaving the Agent abstraction.

```python
agent = Agent(task=steps[0], llm=llm, use_vision=False)
await agent.run(max_steps=1)

for step in steps[1:]:
    agent.add_new_task(step)
    await agent.run(max_steps=1)
```

Browser state persists across calls. Message history accumulates inside the Agent — so per-step prompts grow over time.

### 2.5 Fresh Agent per step, shared session
Most Stagehand-like. New Agent context each step, but same browser.

```python
from browser_use import Agent, BrowserSession

session = BrowserSession()
for step in steps:
    a = Agent(task=step, llm=llm, browser_session=session, use_vision=False)
    await a.run(max_steps=1)
    # a.history -> cache per step
```

Smallest per-step prompt. Each step is an independent LLM call with independent cache key. This is the recommended pattern if the goal is a fair comparison with Stagehand `act()`.

---

## 3. Caching implications

### Stagehand
- Each `act()` is a discrete LLM call. Its cache key is derived from the instruction + accessibility tree snapshot.
- Invalidating one step does not affect the others.
- Cost per run ≈ sum of small, focused calls.

### browser_use default (`Agent.run()` on full task)
- One `AgentHistoryList` per run. `rerun_history()` replays the stored action sequence without new LLM calls — this is deterministic replay, not semantic caching.
- Any change to the task string or DOM structure invalidates the whole history.
- `browser_use/scraper.py` today: full task replayed as a single cached unit.

### browser_use with per-step pattern (2.5)
- One `AgentHistoryList` **per step** — save to `cache/step_{i}.json`.
- Invalidate individual steps without redoing the others.
- Matches Stagehand's cache granularity.

Sketch:

```python
for i, step in enumerate(steps):
    cache_file = cache_dir / f"step_{i}.json"
    a = Agent(task=step, llm=llm, browser_session=session, use_vision=False)
    if use_cache and cache_file.exists():
        history = _load_history_safe(cache_file, a.AgentOutput)
        await a.rerun_history(history)
    else:
        await a.run(max_steps=1)
        if use_cache:
            a.history.save_to_file(cache_file)
```

---

## 4. Caveats

1. **browser_use has no true `act()` primitive.** Every path that involves an LLM goes through the Agent planner. Even with `max_steps=1`, you are running a mini agent loop — system prompt, memory state, DOM serialization, tool schema — not a stripped-down "translate NL to one action" call.

2. **Prompt overhead is structurally higher.** Stagehand `act()` sends minimal context. browser_use Agent always sends the full Agent system prompt and action registry. Expect larger input token counts per step even when the task is atomic.

3. **`add_new_task()` appends; it does not reset.** Using 2.4 across many steps makes each subsequent step more expensive because the message history grows. Pattern 2.5 (fresh Agent per step) avoids this.

4. **`rerun_history()` is replay, not semantic cache.** If the page structure drifts, replay can fail on selector mismatch. Stagehand's cache is keyed on instruction + DOM observation and is more tolerant to drift because the cached output is the action plan, not literal selectors from a prior run. Treat browser_use cache as brittle.

5. **Schema drift breaks cached history.** The existing `_load_history_safe()` in `browser_use/scraper.py` already works around one instance of this (stripping `new_tab` from `navigate` actions). Expect more of these as browser_use evolves.

6. **Vision adds cost asymmetrically.** `use_vision=True` on every per-step Agent call multiplies screenshot tokens. If comparing head-to-head with Stagehand, keep `use_vision=False` to match Stagehand's DOM-only default.

7. **Shared browser session coupling.** Pattern 2.5 relies on `BrowserSession` being reusable across Agents. Verify the installed browser_use version supports it; older versions expected one `Browser` per `Agent`.

8. **Step granularity affects comparability.** Stagehand's "one step" is whatever you write inside `act()`. browser_use counts steps internally. If you hand browser_use a broad step ("find and click the first story"), `max_steps=1` may not be enough — the Agent might need observe + click as two internal steps. Write per-step tasks at the same granularity Stagehand's `act()` expects.

---

## 5. Recommendation

To replicate `act()` as closely as possible in browser_use:

- **Use pattern 2.5**: fresh `Agent(task=step, browser_session=shared_session, max_steps=1)` per step.
- **Cache per step**: one `AgentHistoryList` file per step index, replay via `rerun_history()` on hits.
- **Keep `use_vision=False`** to match Stagehand's default and keep token costs comparable.
- **Keep step instructions atomic** — one observable action per step — so `max_steps=1` is actually sufficient.
- **Accept that per-step prompts will still be larger than Stagehand's.** This is a structural gap, not a tuning issue.

For the `compare.py` benchmark specifically: refactor `browser_use/scraper.py` so `make_task()` returns a list that is driven one item at a time through a shared `BrowserSession`, with per-step history files under `browser_use/cache/step_{i}.json`. This makes the two libraries compare on equal footing: atomic LLM calls, atomic caches, shared browser state.

---

## 6. Quick reference

```
Stagehand act("X")        ≈  Agent(task="X", browser_session=s, max_steps=1).run()
Stagehand observe()       ≈  DomService(page).get_clickable_elements()
Stagehand extract(schema) ≈  @controller.action with Pydantic output_model
Stagehand act cache       ≈  per-step AgentHistoryList saved to disk
```
