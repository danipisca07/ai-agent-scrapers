#!/usr/bin/env python3
"""
Legge tutti i JSON in results/ e stampa una tabella comparativa.
Uso: python compare.py
"""
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def load_all():
    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        print("Nessun risultato trovato. Esegui prima uno dei due scraper.")
        return []
    return [json.loads(f.read_text()) for f in files]


def fmt(v, unit=""):
    if v is None or v == "?":
        return "—"
    return f"{v}{unit}"


def print_runs_table(datasets):
    """Tabella dettagliata: una riga per run."""
    COL = [12, 7, 4, 10, 10, 11, 6, 10]
    HDR = ["Library", "Mode", "Run", "LLM calls", "In tokens", "Out tokens", "Cache", "Duration"]
    sep = "  ".join("-" * w for w in COL)
    row_fmt = "  ".join(f"{{:<{w}}}" for w in COL)

    print("\n" + "=" * 75)
    print("DETTAGLIO RUN")
    print("=" * 75)
    print(row_fmt.format(*HDR))
    print(sep)

    for d in datasets:
        lib  = d["library"]
        mode = d["mode"]
        for r in d["runs"]:
            err = " !" if "error" in r else ""
            print(row_fmt.format(
                lib, mode, str(r["run"]),
                fmt(r.get("llm_calls")),
                fmt(r.get("input_tokens")),
                fmt(r.get("output_tokens")),
                fmt(r.get("cache_hits")),
                fmt(r.get("duration_ms", 0) // 1000, "s") + err,
            ))
    print("=" * 75)


def print_cache_effect(datasets):
    """Mostra l'effetto del caching: run 1 vs media run 2+."""
    print("\nEFFETTO CACHING (run 1 → avg run 2+)")
    print("-" * 55)

    for d in datasets:
        runs = d["runs"]
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
            f"  {d['library']:12} [{d['mode']:5}]  "
            f"calls: {first.get('llm_calls','?')} → {avg_calls:.0f}  "
            f"({reduction_calls:+.0f}%)   "
            f"tokens in: {first.get('input_tokens','?')} → {avg_in:.0f}  "
            f"({reduction_tok:+.0f}%)   "
            f"dur: {first.get('duration_ms',0)//1000}s → {avg_dur/1000:.0f}s"
        )
    print()


def print_summary_table(datasets):
    """Tabella riassuntiva per decidere quale usare."""
    print("RIEPILOGO (totali su tutti i run)")
    print("-" * 75)
    HDR = ["Library", "Mode", "Runs", "Tot calls", "Tot in tok", "Tot out tok", "Avg dur"]
    COL = [12, 7, 4, 10, 11, 12, 10]
    row_fmt = "  ".join(f"{{:<{w}}}" for w in COL)
    print(row_fmt.format(*HDR))
    print("  ".join("-" * w for w in COL))

    for d in datasets:
        runs = d["runs"]
        print(row_fmt.format(
            d["library"], d["mode"], str(len(runs)),
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
