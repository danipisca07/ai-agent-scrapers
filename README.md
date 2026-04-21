# browser-ai-benchmark

Misura LLM calls e token consumati da **Stagehand** e **Browser Use** sullo stesso task
(scraping HackerNews con paginazione) con diverse configurazioni.

## Struttura

```
benchmark/
├── stagehand/       # TypeScript — Stagehand + Playwright
├── browser_use/     # Python — Browser Use (locale o cloud)
├── results/         # JSON output dei run (ignorato da git tranne .gitkeep)
└── compare.py       # Legge results/ e stampa tabella comparativa
```

## Setup

### 1. Variabili d'ambiente

```bash
cp .env.example .env
# Modifica .env con le tue chiavi
```

### 2. Stagehand (Node.js ≥ 18)

```bash
cd stagehand && npm install
```

### 3. Browser Use (Python ≥ 3.11)

```bash
cd browser_use && pip install -r requirements.txt
# Installa Playwright browsers:
playwright install chromium
```

### 4. Ollama (solo per local mode)

```bash
ollama pull llama3.2   # o il modello che preferisci
```

---

## Esecuzione

### Stagehand

```bash
cd stagehand

# Locale (Ollama)
MODE=local MODEL_NAME=llama3.2 PAGES=3 RUNS=3 npm start

# Cloud (Browserbase — richiede BROWSERBASE_API_KEY e PROJECT_ID in .env)
MODE=cloud MODEL_NAME=gpt-4o-mini PAGES=3 RUNS=3 npm start
```

### Browser Use

```bash
cd browser_use

# Locale (Ollama)
MODE=local MODEL_NAME=llama3.2 PAGES=3 RUNS=3 python scraper.py

# Cloud (Browser Use Cloud — richiede BROWSER_USE_API_KEY in .env)
MODE=cloud PAGES=3 RUNS=3 python scraper.py
```

> **RUNS=3** è il parametro chiave per osservare il caching:
> il run 1 è sempre a freddo, dal run 2 in poi si vede se la cache è efficace.

### Confronto

Dopo aver eseguito almeno un run per libreria:

```bash
python compare.py
```

---

## Cosa misura

| Metrica | Descrizione |
|---|---|
| `llm_calls` | Numero di invocazioni LLM per run |
| `input_tokens` | Token di input (prompt) |
| `output_tokens` | Token di output (completion) |
| `cache_hits` | Quante volte la cache è stata usata |
| `duration_ms` | Tempo totale del run |

L'effetto caching si vede confrontando il **run 1** (sempre da zero) con i **run 2-3**:
- Stagehand locale: cache miss se il DOM è cambiato (es. upvote su HN)
- Browser Use Cloud: lo script viene rieseguito diretto, zero LLM calls
