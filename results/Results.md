## Run results

| Run | Stagehand (oss-20b) | Stagehand (llama-scout4) | Browser-use-agent (oss-20b) | Browser-use-agent (llama-scout4) | Browser-use-agent (oss-120b) | Browser-use-act (oss-20b) |
|---|---|---|---|---|---|---|
| 1st run | ✅ | ❌ Failed to generate valid json response | ❌ Went into loop and kept opening same links | ❌ Didn't correcly open all links, even if agent tought it did | ✅ | ✅ |
| 2nd run | ✅ | | |  | ✅ | ✅ |
| 3rd run | ✅ | | |  | ✅ | ✅ |
| 1st re-run after content change | ✅ | | | | ❌ Reopened old content in new position | ❌ Reopened old content in new position |
| 2nd re-run after content change | ✅ | | | | ❌ Reopened old content in new position | ❌ Reopened old content in new position |
| 3rd re-run after content change | ✅ | | | | ❌ Reopened old content in new position | ❌ Reopened old content in new position |
