# Stagehand Act Cache — How It Works

## Cache File Naming

Each cache entry is a JSON file named after a SHA-256 hash computed from three fields:

```js
SHA256(JSON.stringify({ instruction, url, variableKeys }))
```

- **`instruction`**: the trimmed string passed to `stagehand.act()`, e.g. `"Click on story title in rank 7"`
- **`url`**: the current page URL at the time of the act call
- **`variableKeys`**: sorted array of variable placeholder names (empty `[]` if no variables used)

Example: calling `stagehand.act("Click on story title in rank 7")` on `https://news.ycombinator.com/news` always produces the same hash → same filename, regardless of what the page actually contains.

## Cache Entry Structure

```json
{
  "version": 1,
  "instruction": "Click on story title in rank 7",
  "url": "https://news.ycombinator.com/news",
  "variableKeys": [],
  "actions": [
    {
      "selector": "xpath=/html[1]/body[1]/...",
      "description": "link: A Periodic Map of Cheese",
      "method": "click",
      "arguments": []
    }
  ],
  "actionDescription": "link: A Periodic Map of Cheese",
  "message": "Action [click] performed successfully on selector: ..."
}
```

### Field roles during replay

| Field | Used for replay? | Notes |
|---|---|---|
| `selector` | **Yes** | The actual Playwright locator used to find and interact with the element |
| `method` | **Yes** | Playwright method to call (`click`, `fill`, `select`, etc.) |
| `arguments` | **Yes** | Arguments passed to the method (e.g. text to fill) |
| `description` | **Only in self-heal** | Human-readable label; see Self-Heal section below |
| `actionDescription` | **Depends on usage mode** | See note below |
| `message` | **Returned to caller** | Part of the public `act()` return value; recorded in agent replay steps |

**`actionDescription` note:** in plain `stagehand.act()` usage it is returned as part of the result object (informational). In **agent mode** (`stagehand.agent()`), it is fed back to the orchestrating LLM as the confirmation of what action was taken (e.g. `action: result.actionDescription` in the tool response) — this influences the agent's next decision. A stale or misleading `actionDescription` in the cache can therefore cause the agent to reason incorrectly about what happened.

## Normal Cache Hit Flow

1. Cache key computed from `{ instruction, url, variableKeys }`
2. Matching `.json` file found → cache hit
3. For each action in `entry.actions`:
   - Wait for `action.selector` to appear in the DOM
   - Execute `performUnderstudyMethod(page, method, selector, arguments)`
4. **`description` is never read during this path**

## Self-Heal: When the Cached Selector Fails

If the xpath selector fails (element not found or stale), Stagehand's self-heal kicks in — **enabled by default** (`selfHeal ?? true` in `v3.js`). To disable it, pass `selfHeal: false` to the **constructor** (`init()` takes no arguments in local mode).

Self-heal flow:
1. Builds a new instruction from `description`:
   ```js
   const actCommand = `${method} ${action.description}`;
   // e.g. "click link: A Periodic Map of Cheese"
   ```
2. Captures a fresh DOM snapshot
3. Calls the LLM with the snapshot + `actCommand` → gets a new selector
4. Retries the action with the new selector
5. If successful, **updates the cache file** with the new selector

This means `description` is the LLM's fallback signal when the cached xpath breaks.

## Gotchas

### 1. `description` contains dynamic content
The LLM fills `description` with whatever text it saw on the element at recording time (e.g. `"link: A Periodic Map of Cheese"`). If the page content changes between runs (different story titles, rotating banners, etc.), the cached `description` will refer to content that no longer exists. During a normal cache hit this is harmless — `selector` is used. But if the selector also breaks and self-heal runs, the LLM will search for that specific text and fail.

### 2. Structural xpaths are positional, not semantic
The cached xpath is absolute and position-based:
```
xpath=/html[1]/body[1]/center[1]/table[1]/tbody[1]/tr[3]/...tr[19]/td[3]/span[1]/a[1]
```
If the DOM structure changes (extra rows injected, table layout altered), this xpath points to the wrong element or nothing at all. Stagehand does **not** verify that the found element matches the original `description` before clicking.

### 3. Cache key is instruction + URL, not element identity
Two different stories at the same URL with the same instruction string will share the same cache entry. The cache has no awareness of page content — it only knows "this instruction on this URL was handled this way before."

### 4. Cache invalidation is manual
There is no TTL or automatic expiry. A stale cache entry stays forever unless:
- You delete the file manually
- Your code calls the invalidation helper (e.g. `invalidateActCache(instruction, url)` from this project's `index.ts`)
- Self-heal updates the entry with a new selector after a failure

### 5. Self-heal is on by default and costs an LLM call
Self-heal is **enabled by default** (`selfHeal ?? true`). A failed replay triggers a full LLM inference (DOM snapshot + prompt) — same cost as a cache miss. After a successful self-heal the cache is updated, so subsequent runs are fast again. Disable it via the constructor:
```ts
const stagehand = new Stagehand({ ..., selfHeal: false });
```

### 6. `variableKeys` affects cache lookup
If you use variable placeholders (e.g. `%username%`), the keys (not the values) are part of the cache key. A call with `variables: { username: "alice" }` and one with `variables: { username: "bob" }` hit the **same** cache entry. Variable values are substituted at replay time, so one cached action works for all values of the same variable set.

## Recommended Patterns

- **Invalidate on wrong navigation**: if after a cached click you land on the wrong page, delete the cache entry and let the LLM recompute. See `invalidateActCache()` in `index.ts`.
- **Don't rely on self-heal for dynamic pages**: if page content rotates, disable self-heal or accept that a broken selector will cause a hard failure rather than a silent wrong-element click.
- **Keep instructions stable**: any change to the instruction string (trimming aside) produces a different hash → cache miss → LLM call.
- **One cache dir per environment**: if you run against staging and production (different URLs), they will naturally get separate cache entries since URL is part of the key.
