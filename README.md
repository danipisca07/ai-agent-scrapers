# Stagehand vs Browser Use — Browser Automation Benchmark

Measures LLM calls and token consumption for **Stagehand** and **Browser Use** executing the same browser automation task, across different models and execution strategies.

The benchmark runs the same task multiple times in sequence to evaluate caching behavior, and supports re-running after page content changes to test cache invalidation.

Results from a concrete comparison run are documented in [`results/Results.md`](results/Results.md).

---

## Repository structure

```
stagehand-vs-browseruse/
├── stagehand/
│   ├── index.ts           # Stagehand script
│   ├── .env.example
│   └── package.json
├── browser_use/
│   ├── scraper-agent.py   # Browser Use script — full agent mode
│   ├── scraper.py         # Browser Use script — act-equivalent (one agent per step)
│   ├── .env.example
│   └── requirements.txt
├── results/               # JSON output from each run + Results.md summary
└── compare.py             # Reads results/ and prints a comparison table
```

---

## Setup

### Requirements

- Node.js ≥ 18 (for Stagehand)
- Python ≥ 3.11 (for Browser Use)
- A [Groq](https://console.groq.com) API key (both libraries use Groq-hosted models in this benchmark but can be configured to use other providers)

### Stagehand

```bash
cd stagehand
npm install
cp .env.example .env
# Edit .env and set GROQ_API_KEY and MODEL_NAME
```

The script is configured to use GROQ as AI Provider but the library can be easly switched to other major providers, checkout [offical docs](https://docs.stagehand.dev/v3/configuration/models)

### Browser Use

```bash
cd browser_use
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Edit .env and set GROQ_API_KEY and MODEL_NAME
```

The script is configured to use GROQ as AI Provider but the library can be easly switched to other major providers, checkout [offical docs](https://docs.browser-use.com/open-source/supported-models)

---

## Defining your own task

Each script has a clearly marked section where you define what the browser should do. Replace the example task with your own sequence of actions.

### Stagehand — `stagehand/index.ts`

Find the comment block starting at line 78:

```typescript
/**
 * Change the code below to run your own script.
 * ...
 */
await page.goto(`https://news.ycombinator.com/news`, { waitUntil: "domcontentloaded" });

for (let rank = 1; rank <= 10; rank++) {
  await stagehand.act("Click on story title in rank " + rank);
  await page.goBack();
}
```

Replace the `page.goto(...)` and the loop body with your own sequence. You can mix:
- `stagehand.act("natural language instruction")` — LLM-powered, cached per instruction+URL
- Direct Playwright calls — `page.click(...)`, `page.fill(...)`, etc. — no LLM involved

Each `act` call is cached independently by instruction text and page URL, so repeated runs only call the LLM for steps that have not been seen before.

### Browser Use (agent mode) — `browser_use/scraper-agent.py`

Edit the `make_task()` function:

```python
def make_task(n: int) -> list[str]:
    parts = [f"Go to https://news.ycombinator.com/news."]
    for i in range(1, n + 1):
        parts.append(f"click story #{i} title link to open the external link;")
        parts.append(f"then go back to list;")
    parts.append(f"Task done, complete;")
    return parts
```

The list is joined into a single natural-language task string passed to a single Browser Use `Agent`. Replace the URL and the per-step instructions with your own.

### Browser Use (act-equivalent) — `browser_use/scraper.py`

Edit the `make_task()` function in the same way:

```python
def make_task(n: int) -> list[str]:
    parts = [f"Go to https://news.ycombinator.com/news."]
    for i in range(2, n + 2):
        parts.append(f"click story #{i} title link to open the external link;")
        parts.append(f"then go back to list;")
    parts.append(f"Task done, complete;")
    return parts
```

Here each element of the list becomes an independent `Agent` call sharing the same browser session. This keeps per-step context small and behaves more like Stagehand's `act` primitive. Each step's result is cached by the SHA-256 hash of the instruction string.

---

## Running the scripts

All configuration is via environment variables (or the `.env` file in each subdirectory).

| Variable | Default | Description |
|---|---|---|
| `RUNS` | `3` | How many times to execute the full task sequence |
| `MODEL_NAME` | see `.env.example` | model identifier |
| `USE_CACHE` | `true` | Set `false` to force fresh LLM calls and overwrite cache |
| `GROQ_API_KEY` | — | Required |

### Stagehand

```bash
cd stagehand
RUNS=3 MODEL_NAME=groq/openai/gpt-oss-20b npx ts-node index.ts
# or if using the npm start script:
RUNS=3 MODEL_NAME=groq/openai/gpt-oss-20b npm start
```

The model is passed directly via `MODEL_NAME` and forwarded to Stagehand's model config. Check [Groq's model list](https://console.groq.com/docs/models) for available identifiers.

### Browser Use — agent mode

```bash
cd browser_use
source venv/bin/activate
RUNS=3 MODEL_NAME=openai/gpt-oss-120b python scraper-agent.py
```

### Browser Use — act-equivalent

```bash
cd browser_use
source venv/bin/activate
RUNS=3 MODEL_NAME=openai/gpt-oss-20b python scraper.py
```

### Clear cache (force fresh run)

```bash
# Browser Use
USE_CACHE=false python scraper.py

# Stagehand — delete the cache directory
rm -rf stagehand/cache/
```

---

## Output

Each run produces a JSON file in `results/` named after the library, mode, timestamp, and model. Example:

```
results/stagehand_local_1776807967568-1run-oss20b.json
results/browser_use_act_local_1776814885-1run-oss20b.json
```

Each file contains per-run metrics:

```json
{
  "library": "stagehand",
  "model": "groq/openai/gpt-oss-20b",
  "runs": [
    {
      "run": 1,
      "llm_calls": 13,
      "input_tokens": 131521,
      "output_tokens": 5422,
      "cached_input_tokens": 5376,
      "cache_hits": 0,
      "duration_ms": 64696
    }
  ]
}
```

To compare all results in the terminal:

```bash
python compare.py
```

---

## Key findings from the reference run

See [`results/Results.md`](results/Results.md) for the full data. Short version:

- **Stagehand with oss-20b** completed every run correctly, including after page content changed. It used ~131K input tokens on the first run and nearly zero on subsequent runs (fully cached).
- **Browser Use (agent mode)** required oss-120b to succeed, consuming ~283K input tokens. It failed after content changes due to stale cache replay.
- **Browser Use (act-equivalent)** brought the model requirement back down to oss-20b, but token usage remained high (~273K) with the same cache invalidation problem.
