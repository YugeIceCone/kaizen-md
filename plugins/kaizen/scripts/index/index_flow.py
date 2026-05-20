#!/usr/bin/env -S uv run --script
# consolidated-cli-parent: flow
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
#     "torch>=2.0",
#     "sqlite-vec>=0.1.6",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# ///
"""kaizen index_flow — pocketflow-shaped ingest pipeline.

Wraps `onboard_index.do_dump` + `do_filter` as a Node+Flow graph:

```text
   DiscoverNode      walk source tree, list files
        │
        ▼
   DumpNode          INSERT OR REPLACE lossless rows → code_files_raw
        │
        ▼
   FilterEmbedNode   clean + chunk + embed_batch → code_files + code_chunks
        │
        ▼
   OptimizeNode      PRAGMA optimize + FTS5 optimize
        │
        ▼
   ReportNode        write summary to store; emit stats
```

Shared store contract:

Inputs:
  store["root"]      — Path (required)
  store["use_git"]   — bool, default True (False = fs walk)
  store["verbose"]   — bool, default False

Outputs:
  store["files_total"]        — int — code_files_raw row count
  store["files_indexed"]      — int — code_files row count
  store["chunks"]              — int — code_chunks row count
  store["errors"]              — int — raw-stage failures
  store["dropped"]             — int — chunk-stage drops
  store["report"]              — dict — summary for downstream callers
  store["_timing"][NodeClass]  — per-node ms

Same shape-compatible return as `do_index`; can be used as a drop-in
replacement once dependent callers (onboard_mcp.py, cmd_index) opt in.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — until indexers move back / consumers move forward
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
# Reach scripts/workflow for `flow` (post-DOMAIN-12) + scripts/io for _envelope.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workflow"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import flow as _flow  # noqa: E402
import onboard_index as _oi  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-index-flow", tool_version="1.0.0")

class DiscoverNode(_flow.AsyncNode):
    """Walk the source tree; produce the candidate file list. Pure read
    side-effect — does not mutate the db. Splitting this out lets future
    extensions (e.g. an include/exclude filter node) plug between
    discovery and dump."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "root": store["root"],
            "use_git": store.get("use_git", True),
        }

    async def exec_async(self, prep: dict) -> list:
        return await asyncio.to_thread(
            _oi.iter_source_files, prep["root"], prep["use_git"]
        )

    async def post_async(self, store: dict, prep: dict, files: list) -> str:
        store["candidate_files"] = files
        store["candidate_count"] = len(files)
        return "default"

class DumpNode(_flow.AsyncNode):
    """Stage 1 — lossless capture into code_files_raw.

    Wraps `do_dump`. Errors (read / decode) are stored as rows with
    `error IS NOT NULL` — queryable later via `do_raw_errors`."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "root": store["root"],
            "use_git": store.get("use_git", True),
        }

    async def exec_async(self, prep: dict) -> dict:
        return await asyncio.to_thread(
            _oi.do_dump, prep["root"], use_git=prep["use_git"]
        )

    async def post_async(self, store: dict, prep: dict, result: dict) -> str:
        store["dump_result"] = result
        store["files_total"] = result["total"]
        store["errors"] = result["errors"]
        return "default"

class FilterEmbedNode(_flow.AsyncNode):
    """Stage 2 — clean + chunk + embed from code_files_raw.

    Wraps `do_filter`. Reads only from the raw table; safe to re-run
    without re-reading the filesystem."""

    async def prep_async(self, store: dict) -> Path:
        return store["root"]

    async def exec_async(self, root: Path) -> dict:
        return await asyncio.to_thread(_oi.do_filter, root)

    async def post_async(self, store: dict, prep: Path, result: dict) -> str:
        store["filter_result"] = result
        store["files_indexed"] = result["files_indexed"]
        store["chunks"] = result["chunks"]
        store["dropped"] = result["dropped"]
        return "default"

class OptimizeNode(_flow.AsyncNode):
    """PRAGMA optimize + FTS5 optimize as an explicit pipeline stage.

    `do_filter` already does this inline, but exposing it as a Node
    lets callers chain it after non-filter mutations (e.g. quantize
    migration) or skip it entirely via the `optimize=false` store key."""

    async def prep_async(self, store: dict) -> dict:
        return {"root": store["root"], "enabled": store.get("optimize", True)}

    async def exec_async(self, prep: dict) -> bool:
        if not prep["enabled"]:
            return False
        await asyncio.to_thread(self._optimize, prep["root"])
        return True

    @staticmethod
    def _optimize(root: Path) -> None:
        conn = _oi.open_db(root, create=False)
        try:
            try:
                conn.executescript(
                    """
                    INSERT INTO code_chunks_fts(code_chunks_fts) VALUES('optimize');
                    PRAGMA optimize;
                    """
                )
                conn.commit()
            except Exception:
                # FTS mirror missing on pre-v1.28 dbs — only optimize main db.
                conn.execute("PRAGMA optimize")
                conn.commit()
        finally:
            conn.close()

    async def post_async(self, store: dict, prep: dict, ran: bool) -> str:
        store["optimized"] = ran
        return "default"

class ReportNode(_flow.AsyncNode):
    """Terminal — compose the back-compat report dict for the caller.

    Matches `do_index`'s return shape so any consumer can swap the
    flow in without reading the per-stage stores."""

    async def prep_async(self, store: dict) -> dict:
        return store

    async def exec_async(self, store: dict) -> dict:
        return {
            "new": store.get("files_indexed", 0),
            "skipped": (
                store.get("dump_result", {}).get("captured", 0)
                - store.get("files_indexed", 0)
                - store.get("dropped", 0)
            ),
            "stale_removed": store.get("filter_result", {}).get("stale_removed", 0),
            "errors": store.get("errors", 0) + store.get("dropped", 0),
            "total": store.get("files_total", 0),
            "total_chunks": store.get("chunks", 0),
            "new_chunks": store.get("chunks", 0),
            "model": _oi.DEFAULT_MODEL,
            "db": str(_oi.db_path(store["root"])),
            "dump": store.get("dump_result"),
            "filter": store.get("filter_result"),
            "optimized": store.get("optimized", False),
        }

    async def post_async(self, store: dict, prep: dict, report: dict) -> None:
        store["report"] = report
        return None  # terminal

def build_index_flow() -> _flow.AsyncFlow:
    """Construct the canonical ingest flow.

    Discover → Dump → FilterEmbed → Optimize → Report."""
    discover = DiscoverNode()
    dump = DumpNode()
    filter_embed = FilterEmbedNode()
    optimize = OptimizeNode()
    report = ReportNode()
    f = _flow.AsyncFlow(start=discover)
    f.add_successor(discover, "default", dump)
    f.add_successor(dump, "default", filter_embed)
    f.add_successor(filter_embed, "default", optimize)
    f.add_successor(optimize, "default", report)
    return f

def index(root: Path, *, use_git: bool = True, optimize: bool = True) -> dict:
    """Sync wrapper — drop-in shape-compatible with `onboard_index.do_index`."""
    store: dict = {"root": root, "use_git": use_git, "optimize": optimize}
    f = build_index_flow()
    asyncio.run(f.run_async(store))
    return store["report"]

def main():
    import argparse
    import json
    p = argparse.ArgumentParser(
        prog="index_flow.py",
        description="kaizen pocketflow ingest pipeline",
    )
    p.add_argument("--root", default=".", help="project root (default: cwd)")
    p.add_argument("--no-git", action="store_true",
                   help="walk filesystem instead of `git ls-files`")
    p.add_argument("--no-optimize", action="store_true",
                   help="skip the OptimizeNode step")
    p.add_argument("--json", action="store_true")
    p.add_argument("--timing", action="store_true",
                   help="show per-node timing alongside output")
    args = p.parse_args()
    root = Path(args.root).resolve()
    store: dict = {
        "root": root,
        "use_git": not args.no_git,
        "optimize": not args.no_optimize,
    }
    f = build_index_flow()
    asyncio.run(f.run_async(store))
    report = store["report"]
    if args.json:
        _emit(report,
              counts={"new": report.get("new", 0),
                      "errors": report.get("errors", 0),
                      "chunks": report.get("total_chunks", 0)})
    else:
        print(
            f"indexed {report['new']} new, errors {report['errors']}, "
            f"chunks {report['total_chunks']} ({report['db']})",
            file=sys.stderr,
        )
    if args.timing:
        print("--- timing (ms) ---", file=sys.stderr)
        for name, ms in store.get("_timing", {}).items():
            print(f"  {name:<22} {ms} ms", file=sys.stderr)

if __name__ == "__main__":
    main()
