# Analisi: Stagehand vs Browser Use — Caching e Costi in Produzione

> Pubblico: sviluppatori che devono scegliere una delle due per automazione/scraping in produzione.
> Focus esclusivo: sostenibilità economica, strategia di caching, LLM calls per run.

---

## Il problema reale

Un agente browser AI "funziona" in demo. Il problema emerge in produzione quando
lo stesso task viene eseguito centinaia di volte su pagine con **contenuto dinamico**.
Senza caching efficace, ogni run chiama l'LLM da capo → costi che crescono linearmente.

La domanda non è "quale libreria è più intelligente", ma **quale strategia di caching
sopravvive a un DOM che cambia continuamente**.

---

## Stagehand (Browserbase)

### Come funziona il caching locale (`cacheDir`)

Stagehand usa una cache chiave-valore su disco. La chiave è un hash di:

```
hash(istruzione + snapshot DOM corrente)
```

Il **DOM snapshot include il contenuto testuale**, non solo la struttura.

**Conseguenza pratica:** se un contatore (upvote, timestamp, prezzo) cambia tra un run
e il successivo, la chiave cambia → cache miss → chiamata LLM. Su HackerNews questo
accade a ogni refresh perché i punti variano continuamente.

**Non esiste un meccanismo "esegui prima, chiedi all'LLM solo se fallisce".**
Il check avviene prima dell'esecuzione, confrontando il DOM attuale con quello cachato.
Se sono diversi, si riparte da zero.

### Caching cloud (Browserbase Cache)

- Richiede `env: "BROWSERBASE"` + subscription Browserbase.
- Più robusto della cache locale perché gestito lato server con invalidazione intelligente.
- I dettagli implementativi non sono pubblici; in pratica migliora la hit rate rispetto
  alla cache locale ma non elimina il problema fondamentale del content hash.

### Limitazioni in produzione

| Scenario | Comportamento |
|---|---|
| Stessa pagina, stesso contenuto | ✅ Cache hit, zero LLM calls |
| Stessa pagina, 1 numero cambiato | ❌ Cache miss, LLM call completa |
| Pagina diversa, struttura simile | ❌ Cache miss |
| Parametri variabili nel task | ❌ Ogni variante = chiave separata |

### Token tracking (come misurarlo)

Stagehand espone un callback `logger` che riceve ogni evento LLM:

```typescript
logger: (log) => {
  if (log.auxiliary?.usage) {
    calls++;
    inputTokens  += log.auxiliary.usage.promptTokens;
    outputTokens += log.auxiliary.usage.completionTokens;
  }
}
```

---

## Browser Use

### Versione open-source (locale)

- Nessun sistema di caching degli script. Ogni run è un agente LLM completo.
- Con Ollama: costo zero in token monetari, ma latenza alta (il modello gira localmente).
- Adatto per: sviluppo, test, task one-shot non ripetitivi.

### Browser Use Cloud — `cache_script=True`

Questo è il differenziatore principale rispetto a Stagehand.

**Flusso:**

```
Run 1:  task → LLM agent → genera script Playwright Python → eseguito → salvato
Run 2+: stesso task → script eseguito direttamente → ZERO LLM calls
        se fallisce → fast check → (se necessario) LLM judge leggero → rigenera
```

#### Risposta alla domanda: il cache_script è Python puro o usa browser-use?

Lo script generato è **Playwright Python puro** — non dipende dalla libreria
`browser-use` per l'esecuzione. Questo è intenzionale: lo script deve essere
eseguibile senza overhead e senza costi, come un normale script Playwright.

Lo script **non viene restituito direttamente al client** nella risposta: è gestito
lato cloud da Browser Use. Non è possibile analizzarlo o cacharlo lato client
tramite l'API pubblica (almeno nella versione documentata). Se questo è un requisito,
è necessario contattare il team per funzionalità enterprise.

#### Risposta alla domanda: chi fa il "fast check" pre-LLM?

È un semplice **try/except sull'esecuzione Python**. Il flusso è:

```
1. Esegui script  →  successo → done (0 LLM calls)
                  →  eccezione (selector not found, timeout, etc.)
2. Classifica l'errore:
   - Errore transitorio (rete, timeout) → retry, ancora 0 LLM calls
   - Selector non trovato / DOM cambiato strutturalmente → LLM judge
3. LLM judge (modello leggero, pochi token):
   - "Il DOM è cambiato ma la struttura è simile?" → patch minima allo script
   - "Il task è completamente diverso?" → full agent, rigenera lo script
```

Non c'è logica sofisticata pre-LLM: è un normale try/except. La sofisticazione
è nel **come viene classificato l'errore** e nella scelta del modello giusto
(leggero vs. full agent) per gestirlo.

#### Parametri variabili: `@{{placeholder}}`

```python
await client.run(
    task="Search for @{{query}} on @{{site}}",
    variables={"query": "python caching", "site": "HN"},
    cache_script=True,
)
```

Lo script viene generato una volta per template, poi riusato con valori diversi.
Questo è il caso d'uso più potente: stesso script, parametri che cambiano ogni run.

---

## Tabella di confronto

| | Stagehand (locale) | Stagehand (Browserbase) | Browser Use (locale) | Browser Use Cloud |
|---|---|---|---|---|
| **LLM calls run 1** | N per pagina | N per pagina | ~1 task completo | 1 (genera script) |
| **LLM calls run 2+ (stessa pagina)** | 0 se DOM invariato, N altrimenti | migliorato, ma dipende da DOM | N sempre | **0** (script diretto) |
| **LLM calls run 2+ (DOM cambiato)** | N (full restart) | parzialmente cachato | N | 0 → judge leggero se fallisce |
| **Costo per 100 run su pagina dinamica** | alto (quasi tutti miss) | medio-basso | alto (no cache) | **molto basso** |
| **Parametri variabili** | ogni variante = nuova cache key | idem | no cache | ✅ `@{{placeholder}}` |
| **Self-hosted / open-source** | ✅ (senza Browserbase) | ❌ (richiede subscription) | ✅ | ❌ |
| **Linguaggio** | TypeScript | TypeScript | Python | Python |
| **Maturità** | alta | alta | media | beta |
| **Script ispezionabile** | no (cache interna) | no | no | no (cloud-side) |
| **Ollama / modelli locali** | ✅ (via OpenAI-compatible) | ❌ (usa LLM cloud) | ✅ | ❌ |

---

## Quando usare cosa

### Stagehand locale
- Prototipo TypeScript, pagine **statiche o semi-statiche**.
- Task one-shot o con bassa frequenza di ripetizione.
- Vuoi controllare l'intera infrastruttura (no cloud, no subscription).

### Stagehand + Browserbase
- Team TypeScript che vuole browser affidabile in cloud.
- Pagine che cambiano poco (struttura stabile, contenuto che varia lentamente).
- Budget: pay-per-use su Browserbase, accettabile se i task non sono ad alta frequenza.

### Browser Use locale (open-source)
- Sviluppo e testing.
- Task non ripetitivi o che cambiano spesso (non ha senso cachare).
- Vincolo: niente cloud, tutto locale, LLM via Ollama.
- Budget zero (costo computazionale locale).

### Browser Use Cloud
- **Task ripetitivi ad alta frequenza su pagine con contenuto dinamico.**
- Questo è l'unico scenario in cui il ROI è chiaro: costo LLM quasi zero dopo run 1.
- Parametri che variano run-to-run (`@{{placeholder}}`): ideale per scraping
  con query diverse, form fill con dati diversi, ecc.
- Accetti di dipendere da un servizio cloud esterno (no self-hosting).

---

## Cosa misurare con il benchmark

Il repository misura automaticamente per ogni configurazione:

| Metrica | Perché è importante |
|---|---|
| LLM calls run 1 | baseline cost per task |
| LLM calls run 2-3 | caching efficacy |
| Δ calls (run1 → run2+) | la metrica chiave: riduzione % |
| Input tokens | voce di costo principale |
| Cache hits | conferma che la cache funziona |
| Duration | latenza percepita (cache riduce anche quella) |

**Il segnale da cercare:** se Δ calls ≈ 0% su pagina dinamica (HN), la cache è inutile
in produzione. Se Δ calls ≈ -100% (Browser Use Cloud run 2+), la cache regge.

---

## Conclusione

Né Stagehand né Browser Use sono "production ready" out of the box per task
ad alta frequenza su pagine dinamiche.

- **Stagehand** è la scelta più matura per team TypeScript, ma la sua cache
  si invalida troppo facilmente su contenuto dinamico. Richiede Browserbase cloud
  per migliorare la hit rate, e anche lì non elimina il problema fondamentale.

- **Browser Use Cloud** risolve il problema con un modello concettualmente più corretto
  (esegui lo script, chiedi all'LLM solo se fallisce), ma è cloud-only e in beta.

La scelta dipende dalla frequenza dei run e dalla stabilità del DOM target.
Per task eseguiti decine di volte al giorno su pagine con contenuto che cambia,
Browser Use Cloud è l'unica opzione con costi sostenibili. Per tutto il resto,
Stagehand locale o open-source è sufficiente.
