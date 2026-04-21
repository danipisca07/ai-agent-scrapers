import asyncio
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


# ─── Single run ───────────────────────────────────────────────────────────────
async def run_once(run_index: int) -> dict:
    from browser_use.llm.groq.chat import ChatGroq
    from browser_use import Agent

    start = time.time()

    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f"history_{cfg['n_stories']}.json"

    llm = ChatGroq(
        model=cfg["model"],
        api_key=os.environ["GROQ_API_KEY"],
    )
    task = " ".join(make_task(cfg["n_stories"]))
    max_steps = cfg["n_stories"] * 6 + 10
    agent = Agent(task=task, llm=llm, use_vision=False, max_steps=max_steps)

    if cfg["use_cache"] and cache_file.exists():
        try:
            history = _load_history_safe(cache_file, agent.AgentOutput)
            await agent.rerun_history(history)
            return {
                "run":          run_index,
                "llm_calls":    0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_hits":   1,
                "duration_ms":  int((time.time() - start) * 1000),
            }
        except Exception as e:
            return {
                "run":          run_index,
                "llm_calls":    0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_hits":   0,
                "duration_ms":  int((time.time() - start) * 1000),
                "error":        f"cache replay failed: {e}",
            }

    error = None
    try:
        await agent.run()
        if cfg["use_cache"]:
            agent.history.save_to_file(cache_file)
    except Exception as e:
        error = str(e)

    history_entries = agent.token_cost_service.usage_history
    result = {
        "run":                 run_index,
        "llm_calls":           len(history_entries),
        "input_tokens":        sum(e.usage.prompt_tokens for e in history_entries),
        "output_tokens":       sum(e.usage.completion_tokens for e in history_entries),
        "cached_input_tokens": sum(e.usage.prompt_cached_tokens or 0 for e in history_entries),
        "cache_hits":          sum(1 for e in history_entries if (e.usage.prompt_cached_tokens or 0) > 0),
        "duration_ms":         int((time.time() - start) * 1000),
    }
    if error:
        result["error"] = error
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    cache_note = " (cache enabled)" if cfg["use_cache"] else ""
    print(f"\n=== Browser Use  --  local MODE -- {cfg['runs']} runs{cache_note} ===\n")

    run_results = []

    for r in range(1, cfg["runs"] + 1):
        print(f"  run {r}/{cfg['runs']}... ", end="", flush=True)
        m = await run_once(r)
        run_results.append(m)
        ok = f"ERROR: {m['error']}" if "error" in m else "OK"
        cached = " [CACHED]" if m.get("cache_hits", 0) == 1 and m.get("llm_calls", 0) == 0 else ""
        print(
            f"calls:{m['llm_calls']}  in:{m['input_tokens']}  cached_in:{m.get('cached_input_tokens', 0)}  out:{m['output_tokens']}  "
            f"cache:{m['cache_hits']}  {m['duration_ms']}ms  {ok}{cached}"
        )

    output = {
        "library":   "browser_use",
        "mode":      "local",
        "model":     cfg["model"],
        "runs":      run_results,
        "timestamp": datetime.now().isoformat(),
    }

    out_dir = Path(__file__).parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"browser_use_local_{int(time.time())}.json"
    out_file.write_text(json.dumps(output, indent=2))
    print(f"\n-> {out_file}\n")


if __name__ == "__main__":
    asyncio.run(main())
