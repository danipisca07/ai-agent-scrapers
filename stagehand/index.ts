import "dotenv/config";
import { CustomOpenAIClient, Stagehand } from "@browserbasehq/stagehand";
import OpenAI from "openai";
import { z } from "zod";
import fs from "fs";
import path from "path";

const runs = parseInt(process.env.RUNS || "3")
const mode = process.env.MODE === "BROWSERBASE" ? "cloud" : "local";
const model = process.env.MODEL_NAME || "default";

// ─── Metriche ─────────────────────────────────────────────────────────────────
interface RunResult {
  run:           number;
  llm_calls:     number;
  input_tokens:  number;
  output_tokens: number;
  cache_hits:    number;
  duration_ms:   number;
  error?:        string;
}

// ─── Singolo run ──────────────────────────────────────────────────────────────
async function runOnce(runIndex: number): Promise<RunResult> {
  let llm_calls = 0, input_tokens = 0, output_tokens = 0, cache_hits = 0;
  const start = Date.now();
  let storiesTotal = 0;
  let error: string | undefined;

  const stagehand = new Stagehand({
    env:   "LOCAL",
    model: process.env.MODEL_NAME,
    cacheDir: "./cache/stagehand",
    verbose: 2,
    // Tracking tokens via logger
    logger: (logLine: any) => {
      if (logLine?.category === "cache" && logLine?.message?.includes("hit")) {
        cache_hits++;
      }
      if (logLine?.auxiliary?.response?.value === undefined) return;
      const fullResponse = JSON.parse(logLine?.auxiliary?.response?.value);
      if (!fullResponse) return;
      const usage = fullResponse.usage;
      if (usage && usage.inputTokens && usage.outputTokens) {
        llm_calls++;
        input_tokens  += usage.inputTokens;
        output_tokens += usage.outputTokens;
      }
    },
  });

  try {
    await stagehand.init();
    const page = stagehand.context.pages()[0];

    /**
     * 
     * Change the code below to run your own script. 
     * The code below is an example of how to use the Stagehand library to open and interact with a website.
     * Open first page of hacker news and visit the first 10 ranking stories
     */
    await page.goto(`https://news.ycombinator.com/news`, {
      waitUntil: "domcontentloaded",
    });

    for (let rank = 1; rank <= 10; rank++){
      //Open first 10 stories
      await stagehand.act("Open (not upvote) story in rank " + rank); //here the LLM call is cached for each rank (the first run needs to call the LLM 10 times)

      await new Promise(r => setTimeout(r, 500));
      //Go back to list
      await page.goBack();
    }


  } catch (e: any) {
    error = e.message;
  } finally {
    await stagehand.close();
  }

  return {
    run: runIndex,
    llm_calls,
    input_tokens,
    output_tokens,
    cache_hits,
    duration_ms: Date.now() - start,
    ...(error ? { error } : {}),
  };
}

// ─── Main ─────────────────────────────────────────────────────────────────────
async function main() {
  console.log(`\n=== Stagehand  —  ${mode} MODE — ${runs} runs ===\n`);

  const runResults: RunResult[] = [];

  for (let r = 1; r <= runs; r++) {
    process.stdout.write(`  run ${r}/${runs}... `);
    const m = await runOnce(r);
    runResults.push(m);
    const ok = m.error ? `ERROR: ${m.error}` : `OK`;
    console.log(
      `calls:${m.llm_calls}  in:${m.input_tokens}  out:${m.output_tokens}  ` +
      `cache:${m.cache_hits}  ${m.duration_ms}ms  ${ok}`
    );
  }

  const output = {
    library:   "stagehand",
    mode:      mode,
    model:     model,
    runs: runResults,
    timestamp: new Date().toISOString(),
  };

  const outDir = "../results";
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, `stagehand_${mode}_${Date.now()}.json`);
  fs.writeFileSync(outFile, JSON.stringify(output, null, 2));
  console.log(`\n→ ${outFile}\n`);
}

main().catch(console.error);