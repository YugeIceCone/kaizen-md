#!/usr/bin/env python3
"""kaizen flow — async Node+Flow primitives + the canonical example pipeline.

This module IS the kaizen pocketflow runtime — `AsyncNode` and
`AsyncFlow` below are the public primitives that every Node+Flow
pipeline in the plugin imports. The four concrete nodes
(ReadBacklog → DetectPackages → GenerateDocs → WriteReport) are the
canonical reference example: a real workspace pipeline that exercises
each phase + an asyncio.gather fan-out. Reading this file end-to-end
is the recommended way to learn the convention.

## Architecture (Node + Flow + shared store)

Mirrors PocketFlow's API verbatim — `pip install pocketflow` would
let you swap the imports and nothing else. Three-phase nodes; a flow
walks `(node, action) → next` edges until no edge fires.

```text
        ┌─────────────────────────────────────────────────┐
        │             AsyncFlow (orchestrator)            │
        │   self.start ── action_str ──▶ next AsyncNode   │
        └───────────────────┬─────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │       AsyncNode           │
              │  prep_async(store)        │  ① pull inputs
              │       │                   │
              │       ▼                   │
              │  exec_async(prep_res)     │  ② do work
              │       │                   │
              │       ▼                   │
              │  post_async(store, …)     │  ③ write outputs
              │       │                   │     return action_str
              └───────┴───────────────────┘
```

Shared store = a plain `dict`. Nodes read from it in `prep_async` and
write back in `post_async`. No queues, no message-passing rituals.
Action keys are routing labels returned by `post_async`; the default
is `"default"`.

## The reference example pipeline

The four-node pipeline at the bottom of this file is intentionally
non-trivial. It exercises:

- **ReadBacklog** — synchronous-ish file I/O wrapped in
  `asyncio.to_thread` to keep the loop unblocked. Demonstrates the
  read-from-store pattern.
- **DetectPackages** — calls into a sibling helper module
  (`docs_gen.detect_packages`). Demonstrates cross-module reuse.
- **GenerateDocs** — the headline async pattern: `asyncio.gather` over
  N packages. Demonstrates parallel fan-out.
- **WriteReport** — terminal node; demonstrates returning `None` to
  end the flow.

To build your own pipeline (e.g. the upcoming `search_flow.py`):

1. Define each step as an `AsyncNode` subclass with three methods.
2. Instantiate the nodes.
3. Build an `AsyncFlow(start=first_node)` and call
   `flow.add_successor(node, action, next_node)` per edge.
4. Call `await flow.run_async(store)` with the initial shared dict.

## Running the reference example

```bash
python3 flow.py [workspace_root]   # default: cwd
```

Output: JSON summary to stdout with per-node timing (under `_timing`).

## Performance notes

- Each node's wall time is captured under `store["_timing"][NodeClass]`.
- `prep`/`post` should be cheap; `exec` is where the work lives.
- For CPU-bound `exec`, wrap with `asyncio.to_thread(...)` so the
  loop doesn't block. For I/O-bound work, use native awaitables.
- For fan-out, build the task list in `exec_async` and gather.

## Naming history

v1 was `flow_demo.py`. Renamed to `flow.py` in v1.31.0 — once the
search-pipeline port started importing AsyncNode/AsyncFlow from it,
calling it "demo" was misleading. The four reference nodes stay in
this file so new contributors have one place to read end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


# ─── Minimal AsyncNode + AsyncFlow (mirrors PocketFlow API) ──────────


class AsyncNode:
    """Three-phase async node: prep → exec → post."""

    async def prep_async(self, store: dict) -> Any:
        return None

    async def exec_async(self, prep_result: Any) -> Any:
        return None

    async def post_async(self, store: dict, prep_result: Any, exec_result: Any) -> str | None:
        return "default"

    async def run_async(self, store: dict) -> str | None:
        t0 = time.monotonic()
        prep = await self.prep_async(store)
        res = await self.exec_async(prep)
        nxt = await self.post_async(store, prep, res)
        dt_ms = int((time.monotonic() - t0) * 1000)
        store.setdefault("_timing", {})[type(self).__name__] = dt_ms
        return nxt


class AsyncFlow:
    """Linear-or-branching flow. action_key → next_node lookup."""

    def __init__(self, start: AsyncNode) -> None:
        self.start = start
        self.successors: dict[tuple[AsyncNode, str], AsyncNode] = {}

    def add_successor(self, node: AsyncNode, action: str, succ: AsyncNode) -> None:
        self.successors[(node, action)] = succ

    async def run_async(self, store: dict) -> None:
        cur: AsyncNode | None = self.start
        while cur is not None:
            action = await cur.run_async(store) or "default"
            cur = self.successors.get((cur, action))


# ─── Nodes ───────────────────────────────────────────────────────────


class ReadBacklog(AsyncNode):
    """Load backlog.json into the shared store."""

    async def prep_async(self, store: dict) -> str:
        return store["backlog_path"]

    async def exec_async(self, path: str) -> dict:
        return await asyncio.to_thread(self._read, path)

    @staticmethod
    def _read(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {"items": [], "missing": True, "path": path}
        return json.loads(p.read_text())

    async def post_async(self, store: dict, prep: str, backlog: dict) -> str:
        store["backlog"] = backlog
        store["backlog_size"] = len(backlog.get("items", []))
        return "default"


class DetectPackages(AsyncNode):
    """Discover packages in the workspace via docs_gen.detect_packages."""

    async def prep_async(self, store: dict) -> Path:
        return Path(store["workspace_root"])

    async def exec_async(self, root: Path) -> list:
        from docs_gen import detect_packages
        return await asyncio.to_thread(detect_packages, root)

    async def post_async(self, store: dict, prep: Path, packages: list) -> str:
        store["packages"] = packages
        store["package_count"] = len(packages)
        return "default"


class GenerateDocs(AsyncNode):
    """FAN-OUT: scan each package concurrently via asyncio.gather."""

    async def prep_async(self, store: dict) -> tuple[list, Path]:
        return store["packages"], Path(store["workspace_root"])

    async def exec_async(self, prep: tuple[list, Path]) -> list:
        packages, root = prep
        if not packages:
            return []
        from docs_gen import analyze_package
        # The headline async pattern: N packages → N parallel tasks.
        # asyncio.to_thread pushes the blocking file I/O off the loop.
        tasks = [
            asyncio.to_thread(analyze_package, pkg_dir, lang, root)
            for pkg_dir, lang in packages
        ]
        return await asyncio.gather(*tasks)

    async def post_async(self, store: dict, prep: tuple, records: list) -> str:
        store["doc_records"] = records
        return "default"


class WriteReport(AsyncNode):
    """Aggregate stats + emit JSON summary. Terminal node."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "backlog_size": store.get("backlog_size", 0),
            "package_count": store.get("package_count", 0),
            "doc_records": store.get("doc_records", []),
            "timing": store.get("_timing", {}),
            "workspace_root": str(store.get("workspace_root", "")),
        }

    async def exec_async(self, data: dict) -> dict:
        records = data["doc_records"]
        return {
            "workspace_root": data["workspace_root"],
            "backlog_items": data["backlog_size"],
            "packages_detected": data["package_count"],
            "packages_scanned": len(records),
            "total_loc": sum(r["loc"]["total"] for r in records),
            "total_files": sum(r["files"]["total"] for r in records),
            "by_language": dict(Counter(r["language"] for r in records)),
            "top_5_by_loc": [
                {"name": r["name"], "loc": r["loc"]["total"]}
                for r in sorted(records, key=lambda r: -r["loc"]["total"])[:5]
            ],
            "per_node_ms": data["timing"],
        }

    async def post_async(self, store: dict, prep: dict, summary: dict) -> str | None:
        store["summary"] = summary
        print(json.dumps(summary, indent=2))
        return None  # terminal — no successor


# ─── Wiring + entry ──────────────────────────────────────────────────


def resolve_backlog_path(workspace: Path) -> str:
    """Resolve backlog path: prefer .kaizen.toml's backlog_path, else default."""
    config = workspace / ".kaizen.toml"
    if config.exists():
        for line in config.read_text().splitlines():
            line = line.strip()
            if line.startswith("backlog_path"):
                rel = line.split("=", 1)[1].strip().strip('"').strip("'")
                stem = rel.rsplit(".", 1)[0]
                return str(workspace / f"{stem}.json")
    return str(workspace / ".workflow" / "backlog.json")


async def run(workspace: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    store: dict[str, Any] = {
        "workspace_root": workspace,
        "backlog_path": resolve_backlog_path(workspace),
    }

    read = ReadBacklog()
    detect = DetectPackages()
    gen = GenerateDocs()
    report = WriteReport()

    flow = AsyncFlow(read)
    flow.add_successor(read, "default", detect)
    flow.add_successor(detect, "default", gen)
    flow.add_successor(gen, "default", report)

    await flow.run_async(store)


def main() -> None:
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    asyncio.run(run(workspace))


if __name__ == "__main__":
    main()
