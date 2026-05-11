#!/usr/bin/env python3
"""kaizen pocketflow demo v2 — async Node+Flow over real workspace.

Demonstrates the Node+Flow discipline from PocketFlow / shodan's
"Engine + Modes + Nodes" rule, applied to a real artifact: this
plugin's backlog + the surrounding workspace's docs.

Pipeline (4 async nodes, shared store):

    ReadBacklog → DetectPackages → GenerateDocs → WriteReport
                                   (fan-out via      (terminal)
                                    asyncio.gather)

Each node has prep_async / exec_async / post_async phases:
    prep — pull from shared store, validate inputs
    exec — do the real work (possibly I/O-bound)
    post — write results back to store, return action key

GenerateDocs is the interesting one: it fans out per-package doc
scans in parallel — N packages → N concurrent tasks → 1 await.

Run:
    python3 flow_demo.py [workspace_root]

Default: cwd. Output: JSON summary to stdout, with per-node timing.

This file vendors a minimal AsyncNode + AsyncFlow so it has zero
runtime dependencies. The shape mirrors PocketFlow's API exactly; if
you `pip install pocketflow`, swap the imports and nothing else.
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
        from docs_gen import scan_package
        # The headline async pattern: N packages → N parallel tasks.
        # asyncio.to_thread pushes the blocking file I/O off the loop.
        tasks = [
            asyncio.to_thread(scan_package, pkg_dir, lang, root)
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
