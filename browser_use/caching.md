# Browser Use History Cache — How It Works

Browser Use does not cache per-instruction the way Stagehand does. Instead, it records the **entire agent run** (all steps, all interacted elements, all model outputs) into a single JSON history file and replays it end-to-end via `agent.rerun_history(history)`.

## Cache File Naming

In this project (see `scraper.py`), the cache file is named by the task parameter:

```py
cache_file = cache_dir / f"history_{cfg['n_stories']}.json"
```

- The filename is **not** a hash of the task string, URL, or anything semantic.
- Two different tasks that produce the same `n_stories` value overwrite each other.
- The task string itself is not part of the cache key — if you change the task but keep `n_stories`, the existing history file is reused blindly.

This is a convention of *this* project's `scraper.py`, not of the `browser_use` library. The library only provides `agent.history.save_to_file(path)` and `AgentHistoryList.load_from_file(path)` — naming is the caller's responsibility.

## Cache Entry Structure

The file contains an `AgentHistoryList` serialized as JSON:

```json
{
  "history": [
    {
      "model_output": { "action": [ { "click": { "index": 42 } } ], "thinking": "..." },
      "result":       [ { "extracted_content": "...", "include_in_memory": true } ],
      "state": {
        "url":   "https://news.ycombinator.com/news",
        "title": "Hacker News",
        "tabs":  [ { "url": "...", "title": "...", "target_id": "3FAF", "parent_target_id": null } ],
        "screenshot_path": "C:\\...\\step_1.png",
        "interacted_element": [
          {
            "node_id":         67,
            "backend_node_id": 106,
            "frame_id":        null,
            "node_type":       1,
            "node_value":      "",
            "node_name":       "A",
            "attributes":      { "href": "https://example.com" },
            "x_path":          "html/body/center/table/tbody/tr[3]/td/...",
            "element_hash":    7402294363148247424,
            "stable_hash":     7402294363148247424,
            "ax_name":         "Laws of Software Engineering",
            "bounds":          { "x": 184.4, "y": 42.8, "width": 198.9, "height": 16.0 }
          }
        ]
      }
    }
  ]
}
```

### Field roles during replay

| Field | Used for matching? | Notes |
|---|---|---|
| `element_hash` | **Yes — Level 1 (EXACT)** | Full SHA-256 of parent tag path + static attributes + `ax_name` |
| `stable_hash` | **Yes — Level 2 (STABLE)** | Same as `element_hash` but dynamic CSS classes filtered out |
| `x_path` | **Yes — Level 3 (XPATH)** | Positional selector (`tag[n]`). No `text()` / `contains()` |
| `ax_name` + `node_name` | **Yes — Level 4 (AX_NAME)** | Tag + accessibility name |
| `attributes` (`name`, `id`, `aria-label`) | **Yes — Level 5 (ATTRIBUTE)** | Last-resort fallback, in that priority order |
| `node_id`, `backend_node_id` | **No** | Chrome DevTools session-local IDs, unstable across runs |
| `bounds` | **No** | Informational only |
| `frame_id` | **No** | Informational only |
| `screenshot_path` | **No** | Informational only; path may no longer exist on disk |
| `node_value`, `node_type` | **No (direct)** | Implicitly part of hash inputs, not compared standalone |

All matching logic lives in `Agent._update_action_indices()` at `browser_use/agent/service.py:3481-3630`.

## Normal Cache Hit Flow

`scraper.py` checks `cache_file.exists()` and, if true, calls `agent.rerun_history(history)` instead of `agent.run()`. For each step:

1. The agent navigates / waits as the step originally did.
2. The current DOM is rebuilt into `selector_map`.
3. For each cached `interacted_element`, `_update_action_indices()` walks the 5-level cascade (see below) to find a matching element on the live page and rewrites the action's `index` to the new highlight index.
4. The action is executed. If no match is found at any level, the action returns `None` and the step is **skipped silently** — no error, no LLM fallback.

There is **no self-heal equivalent**. Unlike Stagehand, Browser Use will not call the LLM to recover from a broken selector during replay; a failed match just drops the action.

## The 5-Level Cascade

Strategy implemented in `_update_action_indices()` (`browser_use/agent/service.py:3481-3630`). Matching runs in order and stops at the first hit.

### Level 1 — EXACT
```py
elem.element_hash == historical_element.element_hash
```
`element_hash` = SHA-256 of parent tag path + static attributes + `ax_name` (see `dom/views.py:861-887`). Any change to the element's visible text (`ax_name`), to its static attributes, or to its tag ancestry breaks this match.

### Level 2 — STABLE
```py
elem.compute_stable_hash() == historical_element.stable_hash
```
Same inputs as Level 1 but CSS classes matching `DYNAMIC_CLASS_PATTERNS` (`dom/views.py:139-162`) are stripped first. Survives framework-driven class churn (`is-active`, `hover`, `loading`, `dark-mode`, animation classes, etc.). **Still includes `ax_name`** — changing visible text still breaks this.

### Level 3 — XPATH
```py
elem.xpath == historical_element.x_path
```
The xpath is generated by `EnhancedDOMTreeNode.xpath` (`dom/views.py:490-536`) as a purely positional string: tag name plus a 1-based index among siblings of the same tag (`tr[10]`, `td[3]`, etc.). It contains no text predicates, no attribute predicates. Insert a sibling before the target and the xpath silently points to the wrong element.

### Level 4 — AX_NAME
```py
elem.node_name.lower() == historical_element.node_name.lower()
and (elem.ax_node.name if elem.ax_node else None) == historical_element.ax_name
```
Matches by tag + accessibility name anywhere on the page. **Order-independent** — if the original element has moved to a different sibling position, this level still finds it.

### Level 5 — ATTRIBUTE
Tries unique attributes in order: `name`, `id`, `aria-label`. First element with the same tag whose attribute value matches wins.

If all five levels fail, the action is dropped from the replay (returns `None`).

## Gotchas

### 1. Levels 1 and 2 both depend on `ax_name`
The accessibility name (visible text) is part of the hash input at both Level 1 and Level 2. If the element's visible text changes — even if the element itself is the same — both hash levels fail and you fall through to XPath. This is by design: the hash is a *content-aware* identity, not a structural one.

### 2. XPath is purely positional
```
html/body/center/table/tbody/tr[3]/td/table/tbody/tr[10]/td[3]/span/a
```
No `text()`, no `@class`, no `contains()`. If DOM structure changes (rows inserted, wrapper divs added), Level 3 still finds *a* node at that position — it just might be the wrong one. Replay proceeds with no warning.

### 3. Positional-vs-semantic mismatch is silent
Suppose you record a click on story #10 whose title was "X". On replay:

- If "X" has moved to position 15 **and** position 10 no longer exists (shorter list) → Level 3 fails, Level 4 finds "X" at position 15 → click lands on position 15. You wanted position 10, got position 15.
- If "X" has moved to position 15 **but** position 10 still exists (now containing "Y") → Level 3 matches position 10 → click lands on "Y". You wanted "X", got "Y".

Both cases are silent: replay logs a successful match at whichever level fired. Whether the outcome is "correct" depends on whether your script intent is positional or semantic, and the cache cannot know which.

### 4. `node_id`, `backend_node_id`, `bounds`, `frame_id`, `screenshot_path` are not used for matching
They are stored for debugging and informational purposes. A stale screenshot path in the cache is harmless. `node_id` / `backend_node_id` are Chrome DevTools session-scoped and do not survive across runs.

### 5. No automatic invalidation, no TTL
The history file persists until you delete it. In `scraper.py` the cache is only re-generated when the file is missing (or when `USE_CACHE=false` is set in `.env`). There is no hash of the page, the task, or the agent code.

### 6. Naming is the caller's responsibility
`history_{n_stories}.json` is a convention of this project. Change the task but keep `n_stories` → stale cache is reused. If you fork this scraper for a different site or a different task, include enough task identity in the filename.

### 7. Replay errors are caught and reported per-run, not per-action
In `scraper.py`, a raised exception during `rerun_history` is caught and turned into `"error": "cache replay failed: ..."` for the whole run. An action that was silently dropped (no match at any level) does **not** raise — the run is reported as successful while missing work.

### 8. `dom/views.py:DYNAMIC_CLASS_PATTERNS` is a fixed allowlist
Level 2 only forgives the CSS class patterns enumerated at `dom/views.py:139-162`. A custom dynamic class not covered by the patterns will leak into the hash and break Level 2. In that case replay falls back to Level 3 (positional xpath).

### 9. Old history files may lack `stable_hash`
Older runs saved before `stable_hash` existed will skip Level 2 (`dom/views.py:1000` makes it optional). Level 5 (`ATTRIBUTE`) is specifically labeled as a fallback for legacy history files.

## Recommended Patterns

- **Name your cache file by task identity, not by a shallow parameter.** Hash the full task string (or relevant task metadata) into the filename if the task can vary.
- **Decide up front whether your script is positional or semantic, and pick the cache accordingly:**
  - Positional (e.g., "click story #10, whatever it is today") → current cache is fine, just be aware Level 4 can take you off-position if structure changes.
  - Semantic (e.g., "click the Laws of Software Engineering link") → **do not rely on replay alone**. Assert the resulting URL / title after each cached action and invalidate on mismatch.
- **Invalidate on wrong navigation.** After each cached action, verify you landed where you expected. If not, delete the history file and let the agent re-plan.
- **Don't assume replay == original run.** Replay can succeed while silently skipping or mis-targeting actions. Check `agent.history.is_done()` and compare final URL/state against expectations.
- **Delete the history file after DOM restructures.** Site redesigns will invalidate Level 1/2/3 at once; Level 4 (`ax_name`) is the only thing that might still work, and only if your target text is unique on the page.
- **Keep one cache dir per environment and per target site.** URLs in the history are replayed verbatim — a staging-recorded history will hit staging URLs even if you meant to run against production.
