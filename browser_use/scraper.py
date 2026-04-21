import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

cfg = {
    "runs":      int(os.getenv("RUNS", "1")),
    "model":     os.getenv("MODEL_NAME", "openai/gpt-oss-120b"),
    "n_stories": int(os.getenv("N_STORIES", "10")),
}

def make_task(n: int) -> str:
    return (
        f"Navigate to https://news.ycombinator.com/news. "
        f"For each story ranked 1 through {n}: click the story's title link (not the upvote button), "
        f"after the external link opened go back to the list. "
        f"You must visit exactly {n} stories. Once you have visited all {n} stories and returned to the list each time, call done immediately."
    )


# ─── Singolo run ──────────────────────────────────────────────────────────────
async def run_once(run_index: int) -> dict:
    from browser_use.llm.groq.chat import ChatGroq
    from browser_use import Agent

    start = time.time()
    error = None

    llm = ChatGroq(
        model=cfg["model"],
        api_key=os.environ["GROQ_API_KEY"],
    )
    task = make_task(cfg["n_stories"])
    max_steps = cfg["n_stories"] * 6 + 10
    agent = Agent(task=task, llm=llm, use_vision=False, max_steps=max_steps)

    try:
        await agent.run()
    except Exception as e:
        error = str(e)

    history = agent.token_cost_service.usage_history
    llm_calls     = len(history)
    input_tokens  = sum(e.usage.prompt_tokens for e in history)
    output_tokens = sum(e.usage.completion_tokens for e in history)
    cache_hits    = sum(1 for e in history if (e.usage.prompt_cached_tokens or 0) > 0)

    result = {
        "run":           run_index,
        "llm_calls":     llm_calls,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "cache_hits":    cache_hits,
        "duration_ms":   int((time.time() - start) * 1000),
    }
    if error:
        result["error"] = error
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n=== Browser Use  --  local MODE -- {cfg['runs']} runs ===\n")

    run_results = []

    for r in range(1, cfg["runs"] + 1):
        print(f"  run {r}/{cfg['runs']}... ", end="", flush=True)
        m = await run_once(r)
        run_results.append(m)
        ok = f"ERROR: {m['error']}" if "error" in m else "OK"
        print(
            f"calls:{m['llm_calls']}  in:{m['input_tokens']}  out:{m['output_tokens']}  "
            f"cache:{m['cache_hits']}  {m['duration_ms']}ms  {ok}"
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
