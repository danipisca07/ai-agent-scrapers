## Context

The test task consisted of opening the first 10 article links on the Hacker News homepage, one at a time, waiting for each page to load before moving to the next. The same script was run multiple times in sequence to evaluate caching behavior, and then re-run after several hours once the page content had changed (same structure, different articles and potentially different ordering of any articles that were still present).


## Run results

| Run | Stagehand (oss-20b) | Stagehand (llama-scout4) | Browser-use-agent (oss-20b) | Browser-use-agent (llama-scout4) | Browser-use-agent (oss-120b) | Browser-use-act (oss-20b) | Browser-use-act (oss-120b) |
|---|---|---|---|---|---|---|---|
| 1st run | ✅ | ❌ Failed to generate valid json response | ❌ Went into loop and kept opening same links | ❌ Didn't correcly open all links, even if agent tought it did | ✅ | ✅ | ✅ |
| 2nd run | ✅ | | |  | ✅ | ✅ | ✅ |
| 3rd run | ✅ | | |  | ✅ | ✅ | ✅ |
| 1st re-run after content change | ✅ | | | | ❌ Reopened old content in new position | ❌ Reopened old content in new position | ❌ Reopened old content in new position |
| 2nd re-run after content change | ✅ | | | | ❌ Reopened old content in new position | ❌ Reopened old content in new position | ❌ Reopened old content in new position |
| 3rd re-run after content change | ✅ | | | | ❌ Reopened old content in new position | ❌ Reopened old content in new position | ❌ Reopened old content in new position |

## Token consumption (successful runs only)

Format: `input / output / cache_input`

| Run | Stagehand (oss-20b) | Browser-use-agent (oss-120b) | Browser-use-act (oss-20b) | Browser-use-act (oss-120b) |
|---|---|---|---|---|
| 1st run | 131,521 / 5,422 / 5,376 | 283,679 / 19,573 / 0 | 273,805 / 21,687 / 0 | 265,138 / 15,828 / 0 |
| 2nd run | fully cached (10 hits) | fully cached (1 hit) | fully cached (22 hits) | fully cached (22 hits) |
| 3rd run | fully cached (10 hits) | fully cached (1 hit) | fully cached (22 hits) | fully cached (22 hits) |
| 1st re-run after content change | 41,636 / 1,441 / 0 (+ 9 cache hits) | ❌ | ❌ | ❌ |
| 2nd re-run after content change | fully cached (10 hits) | ❌ | ❌ | ❌ |
| 3rd re-run after content change | fully cached (10 hits) | ❌ | ❌ | ❌ |

## Observations

### Stagehand

Stagehand proved to be the most robust solution overall. Its `act` primitive allows fine-grained control over individual browser actions, making it straightforward to combine high-level natural language instructions with direct Playwright calls underneath. This hybrid approach keeps each step small and deterministic.

A key finding is that Stagehand does not require a highly capable model. The primary requirement is the ability to generate structured JSON output conforming to a schema. With `gpt-oss-20b`, the script completed successfully in every run, with occasional retries (2–3 re-executions of the same step) handled by a simple retry logic. `llama-4-scout`, on the other hand, consistently failed to produce valid structured JSON responses, causing the script to error out every time regardless of the run.

After page content changed, Stagehand handled the new state correctly. The first re-run consumed only 41K input tokens (vs 131K for the very first run), as 9 out of 10 steps were already cached — only the steps involving new or repositioned articles required fresh LLM calls.

### Browser Use — Agent mode

Browser Use in full agent mode delegates all reasoning to the LLM, which makes the quality of results heavily model-dependent. With `gpt-oss-20b` and `llama-4-scout`, the agent fell into a loop, repeatedly opening the same links without making progress. With `llama-4-scout` specifically, the agent terminated believing it had succeeded despite not having opened all links. Upgrading to `gpt-oss-120b` resolved the correctness issue, but at the cost of significantly higher token usage (283K input vs Stagehand's 131K for the equivalent task).

### Browser Use — Manual "act" equivalent

To investigate whether a step-by-step decomposition could bring Browser Use closer to Stagehand's behavior, the task was re-implemented by spawning a separate agent instance for each individual instruction. This reduces the context carried across steps and shifts the agent from open-ended reasoning to single-step execution. The result was successful: with this approach, `gpt-oss-20b` was sufficient to complete the task correctly, matching Stagehand's model requirements. Token usage remained high (273K input with oss-20b, 265K with oss-120b) compared to Stagehand, reflecting the overhead of repeated agent initialization and the lack of native structured-output primitives.

### Cache behavior after content change

All Browser Use configurations (both agent and act-equivalent modes) failed when re-run after the page content had changed. The cache replayed the original action sequence, which included opening specific links that had either disappeared or shifted to different positions on the page. Rather than re-evaluating the current page state, the cached execution attempted to interact with stale coordinates or elements, leading to incorrect results in every case. Stagehand did not exhibit this problem.

## Summary

| | Stagehand | Browser Use (agent) | Browser Use (act-equivalent) |
|---|---|---|---|
| Minimum viable model | oss-20b | oss-120b | oss-20b |
| Token efficiency (1st run) | ~137K total | ~303K total | ~295K total |
| Handles content changes | ✅ | ❌ | ❌ |
| Requires structured JSON output | ✅ | ❌ | ❌ |
| Native step decomposition | ✅ (act primitive) | ❌ | manual workaround |


## Compare.py command output after my tests

```
=====================================================================================================
RUN DETAILS
=====================================================================================================
Library       Mode          Model                                           Run   LLM calls   In tokens   Out tokens   Cache   Duration  
------------  ------------  ----------------------                          ----  ----------  ----------  -----------  ------  ----------
browser_use   local-act     openai/gpt-oss-20b                              1     35          273805      21687        0       130s      
browser_use   local-act     openai/gpt-oss-20b                              2     0           0           0            22      163s      
browser_use   local-act     openai/gpt-oss-20b                              3     0           0           0            22      164s      
browser_use   local-act     openai/gpt-oss-120b                             1     35          265138      15828        10      154s      
browser_use   local-act     openai/gpt-oss-120b                             2     0           0           0            22      123s      
browser_use   local-act     openai/gpt-oss-120b                             3     0           0           0            22      134s      
browser_use   local         openai/gpt-oss-120b                             1     22          283679      19573        0       86s       
browser_use   local         openai/gpt-oss-120b                             2     0           0           0            1       103s      
browser_use   local         openai/gpt-oss-120b                             3     0           0           0            1       104s      
browser_use   local         meta-llama/llama-4-scout-17b-16e-instruct       1     33          425569      8819         0       163s !    
browser_use   local         meta-llama/llama-4-scout-17b-16e-instruct       2     0           0           0            0       27s !     
browser_use   local         meta-llama/llama-4-scout-17b-16e-instruct       3     0           0           0            0       31s !     
stagehand     local         groq/openai/gpt-oss-20b                         1     13          131521      5422         0       64s       
stagehand     local         groq/openai/gpt-oss-20b                         2     0           0           0            10      9s        
stagehand     local         groq/openai/gpt-oss-20b                         3     0           0           0            10      9s        
stagehand     local         groq/meta-llama/llama-4-scout-17b-16e-instruct  1     0           0           0            3       13s !     
stagehand     local         groq/meta-llama/llama-4-scout-17b-16e-instruct  2     1           10070       45           2       8s !      
stagehand     local         groq/meta-llama/llama-4-scout-17b-16e-instruct  3     3           30362       709          3       13s !     
stagehand     local         groq/openai/gpt-oss-20b                         1     4           41636       1441         9       242s      
stagehand     local         groq/openai/gpt-oss-20b                         2     0           0           0            10      10s       
stagehand     local         groq/openai/gpt-oss-20b                         3     0           0           0            10      10s       
=====================================================================================================

CACHING EFFECT (run 1 -> avg run 2+)
---------------------------------------------------------------------------
  browser_use  [local-act ] [openai/gpt-oss-20b]
    calls: 35 -> 0  (+100%)   tokens in: 273805 -> 0  (+100%)   dur: 130s -> 164s
  browser_use  [local-act ] [openai/gpt-oss-120b]
    calls: 35 -> 0  (+100%)   tokens in: 265138 -> 0  (+100%)   dur: 154s -> 129s
  browser_use  [local     ] [openai/gpt-oss-120b]
    calls: 22 -> 0  (+100%)   tokens in: 283679 -> 0  (+100%)   dur: 86s -> 104s
  browser_use  [local     ] [meta-llama/llama-4-scout-17b-16e-instruct]
    calls: 33 -> 0  (+100%)   tokens in: 425569 -> 0  (+100%)   dur: 163s -> 30s
  stagehand    [local     ] [groq/openai/gpt-oss-20b]
    calls: 13 -> 0  (+100%)   tokens in: 131521 -> 0  (+100%)   dur: 64s -> 10s
  stagehand    [local     ] [groq/meta-llama/llama-4-scout-17b-16e-instruct]
    calls: 0 -> 2  (-100%)   tokens in: 0 -> 20216  (-2021500%)   dur: 13s -> 11s
  stagehand    [local     ] [groq/openai/gpt-oss-20b]
    calls: 4 -> 0  (+100%)   tokens in: 41636 -> 0  (+100%)   dur: 242s -> 10s

SUMMARY (totals across all runs)
-----------------------------------------------------------------------------------------------------
Library       Mode          Model                                           Runs  Tot calls   Tot in tok   Tot out tok   Avg dur   
------------  ------------  ----------------------                          ----  ----------  -----------  ------------  ----------
browser_use   local-act     openai/gpt-oss-20b                              3     35          273805       21687         152s      
browser_use   local-act     openai/gpt-oss-120b                             3     35          265138       15828         137s      
browser_use   local         openai/gpt-oss-120b                             3     22          283679       19573         98s       
browser_use   local         meta-llama/llama-4-scout-17b-16e-instruct       3     33          425569       8819          74s       
stagehand     local         groq/openai/gpt-oss-20b                         3     13          131521       5422          27s       
stagehand     local         groq/meta-llama/llama-4-scout-17b-16e-instruct  3     4           40432        754           11s       
stagehand     local         groq/openai/gpt-oss-20b                         3     4           41636        1441          87s

```