# Node + Flow — the kaizen async pipeline primitive

Lives at `scripts/flow.py`. Pure-Python (stdlib + asyncio). The plugin
uses this shape for every multi-stage pipeline that needs explicit
state transitions, parallel fan-out, or replay/inspection — search,
scrape, doc-gen, indexers.

This reference covers: the API, the three lifecycle phases, the
shared-store contract, action-based routing, fan-out via
`asyncio.gather`, error handling, and the migration path to
`pip install pocketflow` if you want the upstream package.

---

## TL;DR

```python
from flow import AsyncNode, AsyncFlow


class ReadInput(AsyncNode):
    async def prep_async(self, store):       return store["raw_path"]
    async def exec_async(self, path):         return await asyncio.to_thread(Path(path).read_text)
    async def post_async(self, store, p, r):  store["raw"] = r; return "default"


class ParseInput(AsyncNode):
    async def prep_async(self, store):       return store["raw"]
    async def exec_async(self, raw):          return json.loads(raw)
    async def post_async(self, store, p, r):  store["parsed"] = r; return "default"


read, parse = ReadInput(), ParseInput()
flow = AsyncFlow(start=read)
flow.add_successor(read, "default", parse)

await flow.run_async({"raw_path": "/tmp/in.json"})
```

That's the full API. Three methods per node, one edge-table per
flow, one dict for everything else.

---

## The two primitives

### `AsyncNode`

A single executable step. Three lifecycle methods, all optional —
override the ones you need:

| Method | Purpose | Returns |
|---|---|---|
| `prep_async(store)` | Pull inputs from the shared store; validate; resolve paths. **Cheap.** | The `prep_res` passed to `exec_async`. Whatever shape you want. |
| `exec_async(prep_res)` | Do the real work. May `await` external I/O, may `asyncio.to_thread(...)` CPU-bound calls. | The `exec_res` passed to `post_async`. Whatever shape you want. |
| `post_async(store, prep_res, exec_res)` | Write outputs back to the shared store; emit a routing action. **Cheap.** | The action key (`str` or `None`). Default → `"default"`. |

The base class `run_async(store)` chains all three and records wall
time under `store["_timing"][NodeClass]` for later inspection.

### `AsyncFlow`

A `(node, action) → next_node` edge table plus a start node.

| Method | Purpose |
|---|---|
| `AsyncFlow(start)` | Constructor — `start` is the first node to run. |
| `flow.add_successor(node, action, next_node)` | Register an edge: when `node` returns `action` from `post_async`, run `next_node`. |
| `flow.run_async(store)` | Walk the graph starting from `start` until a node returns `None` or an action with no registered successor. Mutates `store` in place. |

---

## Shared store

A plain `dict`. The flow passes it through every `prep_async` and
`post_async` call. Nodes communicate via writes; readers see whatever
the previous post left.

**Conventions in kaizen:**

- Inputs go in at the top: `await flow.run_async({"workspace_root": ".", "backlog_path": "...", ...})`.
- Each node prefixes its outputs with its purpose: `store["raw"]`, `store["parsed"]`, `store["embedded"]` rather than overwriting a single `store["data"]`.
- `store["_timing"]` is auto-populated by `run_async` — don't write there yourself.
- Avoid mutable shared objects across nodes; prefer fresh dicts/lists per write.

**Anti-pattern:** treating the store like a singleton — adding helper
classes or stateful objects that nodes mutate through method calls.
Keep it dumb data; behaviors belong inside nodes.

---

## Lifecycle in detail

```text
                ┌───────────────┐
                │ flow.run_async│  driver — walks the edge table
                └───────┬───────┘
                        │
                        ▼
              ┌─────────────────────┐
              │ node.run_async(store)│   (per node)
              └─────────┬───────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   prep_async       exec_async       post_async
   (read store)     (do work)        (write store +
                                       return action)
        │               │               │
        └──── prep_res ─┴── exec_res ───┘
```

### Why three phases instead of one?

- **Testability** — exec is the only side-effectful step; you can
  unit-test it by feeding a literal `prep_res` without setting up a
  store.
- **Resumability** — a future `replay(store, from=NodeName)` driver
  only needs to skip `exec_async` for nodes whose post already wrote
  the right outputs.
- **Observability** — the `_timing` record breaks down per-phase if
  you want it to (override `run_async` and time each phase).
- **Refactor-friendly** — moving work between prep/exec/post stays
  inside one class; you don't fracture the node.

---

## Routing: action keys

`post_async` returns a string that selects the next node:

```python
class ValidateInput(AsyncNode):
    async def post_async(self, store, prep_res, is_valid):
        return "valid" if is_valid else "invalid"

# Same source node, two outgoing edges:
flow.add_successor(validate, "valid",   process)
flow.add_successor(validate, "invalid", error_handler)
```

Conventions:

- `"default"` — the unconditional next step. Use when there's no branch.
- Domain-specific strings (`"empty"`, `"retry"`, `"halt"`) — branch labels.
- `None` — terminate the flow at this node.
- Returning an action with no registered edge — terminates the flow
  silently. Useful for "stop here" patterns; surprising otherwise.

---

## Fan-out: `asyncio.gather`

Parallel work happens inside `exec_async`:

```python
class FetchAll(AsyncNode):
    async def prep_async(self, store):
        return store["urls"]

    async def exec_async(self, urls):
        tasks = [self._fetch(u) for u in urls]
        return await asyncio.gather(*tasks)

    async def post_async(self, store, urls, responses):
        store["responses"] = responses
        return "default"

    async def _fetch(self, url):
        # ... aiohttp / httpx / urllib in to_thread / etc.
        ...
```

For CPU-bound work, wrap with `asyncio.to_thread(fn, *args)` so the
loop stays unblocked:

```python
async def exec_async(self, items):
    tasks = [asyncio.to_thread(self._cpu_bound, item) for item in items]
    return await asyncio.gather(*tasks)
```

The reference example's `GenerateDocs` node is exactly this pattern:
N packages → N `to_thread(analyze_package, ...)` tasks → one gather.

---

## Error handling

The base `run_async` does NOT catch exceptions. If `exec_async`
raises, the flow stops and the exception propagates. **This is
deliberate** — silent retries hide real bugs.

If you need retries, build them into the node's `exec_async`:

```python
class WithRetry(AsyncNode):
    MAX_RETRIES = 3

    async def exec_async(self, prep_res):
        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._try_once(prep_res)
            except TransientError:
                if attempt + 1 == self.MAX_RETRIES:
                    raise
                await asyncio.sleep(0.5 * (2 ** attempt))
```

If you need a fallback (graceful degrade), branch in `post_async`:

```python
class FetchWithFallback(AsyncNode):
    async def exec_async(self, url):
        try:
            return await self._primary(url)
        except PrimaryDown:
            return None  # signal failure

    async def post_async(self, store, url, result):
        if result is None:
            return "fallback"
        store["result"] = result
        return "default"

flow.add_successor(fetch, "default",  use_result)
flow.add_successor(fetch, "fallback", fallback_node)
```

---

## Where the primitive is used (and where it will be)

| Module | Pipeline | Status |
|---|---|---|
| `flow.py` | ReadBacklog → DetectPackages → GenerateDocs → WriteReport | reference example (canonical) |
| `scrape_index.py` | FetchURLs → ScrapeFanOut → Synthesize → Embed → Persist | live, used by `kaizen-scrape` |
| `search_flow.py` (planned, v1.31.0+) | EmbedQuery → DenseSearch / BM25 (parallel) → Fusion → Rerank → Citation | porting onboard semantic-search to this shape |

---

## Migrating to upstream PocketFlow

`pip install pocketflow` gives you the same Node/Flow shape, with
extras (sync nodes, batch flows, retry decorators). The vendored
classes here use `prep_async`/`exec_async`/`post_async` (matches
PocketFlow's async API). To swap:

```python
# Before (vendored):
from flow import AsyncNode, AsyncFlow

# After (upstream):
from pocketflow import AsyncNode, AsyncFlow
```

That's it. The shape is verbatim.

We vendor the minimal version because: zero pip deps for the
plugin's default install, the file is 60 LOC of base classes, and
upstream's surface is broader than the plugin's needs.

---

## Cross-references

- Source: `scripts/flow.py`
- Bash wrapper: `bin/kaizen-flow` (the slash form was retired — bin remains as the educational reference + smoke target)
- Upstream: [the-pocket/pocketflow](https://github.com/the-pocket/pocketflow) (the original 100-line LLM framework)
- Shodan's port: `crates/retrieval/src/runtime/{flow,node}.rs` — same shape in Rust, with sync nodes + a `FlowRunner` orchestrator
- Related skill: see `skills/workflow/SKILL.md` § "Engine + Modes + Nodes" for the broader discipline that motivates Node+Flow as the canonical LLM-orchestration shape across kaizen + shodan
