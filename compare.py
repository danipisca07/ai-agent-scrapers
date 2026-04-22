#!/usr/bin/env python3
"""
Reads all JSON files in results/ and prints a comparative table.
Usage: python compare.py
"""
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def load_all():
    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        print("No results found. Run one of the scrapers first.")
        return []
    return [json.loads(f.read_text()) for f in files]


def fmt(v, unit=""):
    if v is None or v == "?":
        return "—"
    return f"{v}{unit}"


def print_runs_table(datasets):
    """Detailed table: one row per run."""
    COL = [12, 12, 22, 4, 10, 10, 11, 6, 10]
    HDR = ["Library", "Mode", "Model", "Run", "LLM calls", "In tokens", "Out tokens", "Cache", "Duration"]
    sep = "  ".join("-" * w for w in COL)
    row_fmt = "  ".join(f"{{:<{w}}}" for w in COL)

    print("\n" + "=" * 101)
    print("RUN DETAILS")
    print("=" * 101)
    print(row_fmt.format(*HDR))
    print(sep)

    for d in datasets:
        lib   = d["library"]
        mode  = d["mode"]
        model = d.get("model", "unknown")
        for r in d["runs"]:
            err = " !" if "error" in r else ""
            print(row_fmt.format(
                lib, mode, model, str(r["run"]),
                fmt(r.get("llm_calls")),
                fmt(r.get("input_tokens")),
                fmt(r.get("output_tokens")),
                fmt(r.get("cache_hits")),
                fmt(r.get("duration_ms", 0) // 1000, "s") + err,
            ))
    print("=" * 101)


def print_cache_effect(datasets):
    """Shows caching effect: run 1 vs avg run 2+."""
    print("\nCACHING EFFECT (run 1 -> avg run 2+)")
    print("-" * 75)

    for d in datasets:
        runs  = d["runs"]
        model = d.get("model", "unknown")
        if len(runs) < 2:
            continue
        first = runs[0]
        rest  = runs[1:]

        avg_calls = sum(r.get("llm_calls", 0) for r in rest) / len(rest)
        avg_in    = sum(r.get("input_tokens", 0) for r in rest) / len(rest)
        avg_dur   = sum(r.get("duration_ms", 0) for r in rest) / len(rest)

        reduction_calls = (1 - avg_calls / max(first.get("llm_calls", 1), 1)) * 100
        reduction_tok   = (1 - avg_in / max(first.get("input_tokens", 1), 1)) * 100

        print(
            f"  {d['library']:12} [{d['mode']:10}] [{model}]\n"
            f"    calls: {first.get('llm_calls','?')} -> {avg_calls:.0f}  ({reduction_calls:+.0f}%)   "
            f"tokens in: {first.get('input_tokens','?')} -> {avg_in:.0f}  ({reduction_tok:+.0f}%)   "
            f"dur: {first.get('duration_ms',0)//1000}s -> {avg_dur/1000:.0f}s"
        )
    print()


def print_summary_table(datasets):
    """Summary table to decide which library to use."""
    print("SUMMARY (totals across all runs)")
    print("-" * 101)
    HDR = ["Library", "Mode", "Model", "Runs", "Tot calls", "Tot in tok", "Tot out tok", "Avg dur"]
    COL = [12, 12, 22, 4, 10, 11, 12, 10]
    row_fmt = "  ".join(f"{{:<{w}}}" for w in COL)
    print(row_fmt.format(*HDR))
    print("  ".join("-" * w for w in COL))

    for d in datasets:
        runs  = d["runs"]
        model = d.get("model", "unknown")
        print(row_fmt.format(
            d["library"], d["mode"], model, str(len(runs)),
            str(sum(r.get("llm_calls", 0) for r in runs)),
            str(sum(r.get("input_tokens", 0) for r in runs)),
            str(sum(r.get("output_tokens", 0) for r in runs)),
            f"{sum(r.get('duration_ms',0) for r in runs) // len(runs) // 1000}s",
        ))
    print()


if __name__ == "__main__":
    data = load_all()
    if not data:
        exit(1)

    print_runs_table(data)
    print_cache_effect(data)
    print_summary_table(data)
