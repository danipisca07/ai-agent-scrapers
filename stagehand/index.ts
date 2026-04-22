import "dotenv/config";
import { CustomOpenAIClient, Stagehand } from "@browserbasehq/stagehand";
import OpenAI from "openai";
import { registry, z } from "zod";
import fs from "fs";
import path from "path";
import crypto from "crypto";

const CACHE_DIR = path.resolve("./cache/stagehand");

function invalidateActCache(instruction: string, pageUrl: string): void {
  const key = crypto
    .createHash("sha256")
    .update(JSON.stringify({ instruction: instruction.trim(), url: pageUrl, variableKeys: [] }))
    .digest("hex");
  const file = path.join(CACHE_DIR, `${key}.json`);
  try { fs.unlinkSync(file); } catch { /* not cached, ignore */ }
}

const runs = parseInt(process.env.RUNS || "3")
const mode = process.env.MODE === "BROWSERBASE" ? "cloud" : "local";
const model = process.env.MODEL_NAME || "default";

// ─── Metriche ─────────────────────────────────────────────────────────────────
interface RunResult {
  run:                  number;
  llm_calls:            number;
  input_tokens:         number;
  output_tokens:        number;
  cached_input_tokens:  number;
  cache_hits:           number;
  duration_ms:          number;
  error?:               string;
}

// ─── Singolo run ──────────────────────────────────────────────────────────────
async function runOnce(runIndex: number): Promise<RunResult> {
  let llm_calls = 0, input_tokens = 0, output_tokens = 0, cached_input_tokens = 0, cache_hits = 0;
  const start = Date.now();
  let storiesTotal = 0;
  let error: string | undefined;

  const stagehand = new Stagehand({
    env:   "LOCAL",
    model: process.env.MODEL_NAME,
    selfHeal: false,
    // llmClient: new CustomOpenAIClient({
    //   modelName: "qwen3.5:9b",
    //   client: new OpenAI({
    //       apiKey: "ollama",
    //       baseURL: "http://localhost:11434/v1"
    //     }),
    //   }),
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
        cached_input_tokens += usage.cachedInputTokens;
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

    let retries = 0;
    const max_retries = 3;
    for (let rank = 1; rank <= 10;){
      try {
        //Open first 10 stories
        let options = {
          //model: retries > 0 ? "groq/openai/gpt-oss-120b" : process.env.MODEL_NAME //You can use this to upgrade model when retring
        }
        let action = "Click on story title in rank " + rank
        var actRes = await stagehand.act(action, options); //here the LLM call is cached for each rank (the first run needs to call the LLM 10 times)

        await new Promise(r => setTimeout(r, 500));

        const currentUrl = page.url();
        const actionIsValid = !currentUrl.includes("ycombinator.com");

        //Go back to list
        await page.goBack();

        if (actionIsValid){
          if(retries > 0)
            console.log("Rank " + rank + " completed after " + retries + " retries.")
          rank++;
          retries = 0;
        } else  {
          invalidateActCache(action, "https://news.ycombinator.com/news");
          retries++;
        }

        if(retries>max_retries)
          throw "Even after retrying " + (retries - 1) + " times didn't manage to navigate to link in rank " + rank;
      } catch (e: any ){
        if (e.message?.includes("-32000")) {
          // CDP context destroyed by navigation — navigate back and continue
          //await page.goto("https://news.ycombinator.com/news", { waitUntil: "domcontentloaded" });
        } else {
          if(retries < max_retries)
            retries++;
          else 
            throw e;
        }
      }
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
    cached_input_tokens,
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
      `calls:${m.llm_calls}  in:${m.input_tokens}  cached_in:${m.cached_input_tokens}  out:${m.output_tokens}  ` +
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