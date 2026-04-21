import asyncio
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

cfg = {
    "runs":      int(os.getenv("RUNS", "3")),
    "model":     os.getenv("MODEL_NAME", "openai/gpt-oss-120b"),
    "n_stories": int(os.getenv("N_STORIES", "10")),
    "use_cache": os.getenv("USE_CACHE", "true").lower() == "true",
}


def make_task(n: int) -> list[str]:
    parts = [f"Go to https://news.ycombinator.com/news."]
    for i in range(1, n + 1):
        parts.append(f"click story #{i} title link to open the external link;")
        parts.append(f"then go back to list;")
    parts.append(f"Task done, complete;")
    return parts


def _cache_filename(instruction: str) -> str:
    h = hashlib.sha256(instruction.strip().encode("utf-8")).hexdigest()[:16]
    return f"act_{h}.json"


def _load_history_safe(cache_file: Path, output_model):
    """Load history JSON, stripping stale action fields that no longer exist in the schema."""
    import copy
    from browser_use.agent.views import AgentHistoryList

    with open(cache_file, encoding="utf-8") as f:
        data = json.load(f)

    data = copy.deepcopy(data)
    for entry in data.get("history", []):
        mo = entry.get("model_output")
        if not mo or not isinstance(mo, dict):
            continue
        for action in mo.get("action", []):
            if not isinstance(action, dict):
                continue
            navigate_params = action.get("navigate")
            if isinstance(navigate_params, dict):
                navigate_params.pop("new_tab", None)

    return AgentHistoryList.load_from_dict(data, output_model)


# ─── Single act primitive ─────────────────────────────────────────────────────
async def _act(instruction: str, llm, browser_session, cache_dir: Path) -> dict:
    """Replicate Stagehand's page.act(): one instruction -> one LLM call, cached by instruction hash."""
    from browser_use import Agent

    cache_file = cache_dir / _cache_filename(instruction)
    agent = Agent(
        task=instruction,
        llm=llm,
        browser_session=browser_session,
        use_vision=False,
    )

    metrics = {
        "llm_calls":           0,
        "input_tokens":        0,
        "output_tokens":       0,
        "cached_input_tokens": 0,
        "cache_hits":          0,
        "error":               None,
    }

    if cfg["use_cache"] and cache_file.exists():
        try:
            history = _load_history_safe(cache_file, agent.AgentOutput)
            await agent.rerun_history(history)
            metrics["cache_hits"] = 1
            return metrics
        except Exception as e:
            metrics["error"] = f"cache replay failed: {e}"
            # fall through to live run

    try:
        # max_steps=2, not 1: with max_steps=1 browser_use flags step 0 as the
        # last step and forces the LLM into a done-only schema, so the click
        # never fires. With max_steps=2 the first call executes the action and
        # the second (forced-done) call closes the act.
        await agent.run(max_steps=2)
        if cfg["use_cache"] and metrics["error"] is None:
            agent.history.save_to_file(cache_file)
    except Exception as e:
        metrics["error"] = str(e)

    for entry in agent.token_cost_service.usage_history:
        metrics["llm_calls"]           += 1
        metrics["input_tokens"]        += entry.usage.prompt_tokens
        metrics["output_tokens"]       += entry.usage.completion_tokens
        metrics["cached_input_tokens"] += entry.usage.prompt_cached_tokens or 0

    return metrics


# ─── Single run ───────────────────────────────────────────────────────────────
async def run_once(run_index: int) -> dict:
    from browser_use.llm.groq.chat import ChatGroq
    from browser_use import BrowserSession

    start = time.time()

    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)

    llm = ChatGroq(
        model=cfg["model"],
        api_key=os.environ["GROQ_API_KEY"],
    )
    steps = make_task(cfg["n_stories"])

    agg = {
        "llm_calls":           0,
        "input_tokens":        0,
        "output_tokens":       0,
        "cached_input_tokens": 0,
        "cache_hits":          0,
    }
    error = None

    session = BrowserSession(keep_alive=True)
    try:
        for step in steps:
            m = await _act(step, llm, session, cache_dir)
            for k in agg:
                agg[k] += m[k]
            if m["error"]:
                error = m["error"]
                break
    finally:
        try:
            await session.kill()
        except Exception:
            pass

    result = {
        "run":         run_index,
        **agg,
        "duration_ms": int((time.time() - start) * 1000),
    }
    if error:
        result["error"] = error
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    cache_note = " (cache enabled)" if cfg["use_cache"] else ""
    print(f"\n=== Browser Use (act mode)  --  local MODE -- {cfg['runs']} runs{cache_note} ===\n")

    run_results = []

    for r in range(1, cfg["runs"] + 1):
        print(f"  run {r}/{cfg['runs']}... ", end="", flush=True)
        m = await run_once(r)
        run_results.append(m)
        ok = f"ERROR: {m['error']}" if "error" in m else "OK"
        print(
            f"calls:{m['llm_calls']}  in:{m['input_tokens']}  cached_in:{m['cached_input_tokens']}  out:{m['output_tokens']}  "
            f"cache:{m['cache_hits']}  {m['duration_ms']}ms  {ok}"
        )

    output = {
        "library":   "browser_use",
        "mode":      "local-act",
        "model":     cfg["model"],
        "runs":      run_results,
        "timestamp": datetime.now().isoformat(),
    }

    out_dir = Path(__file__).parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"browser_use_act_local_{int(time.time())}.json"
    out_file.write_text(json.dumps(output, indent=2))
    print(f"\n-> {out_file}\n")


if __name__ == "__main__":
    asyncio.run(main())
