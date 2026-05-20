#!/usr/bin/env python3
# consolidated-cli-parent: flow
"""kaizen flow docs — pocketflow-shaped per-crate documentation pipeline.

Wraps `docs_gen.detect_packages` + per-package `analyze_package` +
`render_md` + write as a Node+Flow graph with `asyncio.gather` fan-out:

```text
   DetectPackagesNode      walk workspace for Cargo.toml / pyproject.toml / package.json / go.mod
        │
        ▼
   AnalyzePackagesNode     FAN-OUT — N packages → asyncio.gather(analyze_package * N)
        │
        ▼
   RenderNode              per-profile render_md + to_json
        │
        ▼
   WriteNode               write <NAME>.{md,json} to output dir
        │
        ▼
   ReportNode              summary dict for stdout / JSON
```

Shared store contract:

Inputs:
  store["root"]       — Path (required)  — workspace root
  store["output_dir"] — Path (required)  — where to emit md/json
  store["format"]     — "json" | "md" | "both" (default "both")
  store["port"]       — bool, default False (use `port/` header instead of `crates/`)
  store["only"]       — Optional[set[str]] — restrict to package leaf names

Outputs:
  store["packages"]    — list of (Path, language) tuples
  store["profiles"]    — list[CrateProfile]
  store["rendered"]    — list[dict] — per-profile {stem, md?, json?}
  store["written"]     — list[str] — emitted filenames (relative to root)
  store["report"]      — dict — summary {package_count, files_written, ...}
  store["_timing"][NodeClass] — per-node ms

Sync wrapper `docs_scan(root, output_dir, ...)` is shape-compatible
with `docs_gen.cmd_scan`'s side effects — same files emitted, same
naming convention.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — cross-cluster sibs still at legacy or shimmed there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import flow as _flow  # noqa: E402
import docs_gen as _dg  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-docs-flow", tool_version="1.0.0")

class DetectPackagesNode(_flow.AsyncNode):
    """Walk the workspace tree; produce (package_dir, language) tuples."""

    async def prep_async(self, store: dict) -> Path:
        return store["root"]

    async def exec_async(self, root: Path) -> list[tuple[Path, str]]:
        return await asyncio.to_thread(_dg.detect_packages, root)

    async def post_async(self, store: dict, prep: Path,
                         packages: list[tuple[Path, str]]) -> str:
        only: Optional[set[str]] = store.get("only")
        if only:
            packages = [(p, l) for p, l in packages if p.name in only]
        store["packages"] = packages
        store["package_count"] = len(packages)
        if not packages:
            return "empty"
        return "default"

class AnalyzePackagesNode(_flow.AsyncParallelBatchNode):
    """FAN-OUT: analyze N packages in parallel via AsyncParallelBatchNode.

    Each analyze_package call is CPU-bound (regex over source files),
    so `to_thread` lets the event loop schedule them. At workspace
    scale (~25 crates × ~50 files each), this completes in <2s end-to-end.

    Per the iron-law node-flow-for-multi-step: fan-outs use
    AsyncParallelBatchNode rather than raw asyncio.gather, so retry +
    cycle-guard + event-hook tracing apply uniformly."""

    async def prep_async(self, store: dict) -> list:
        # Pass tuples (pkg_dir, lang, root) — exec_one_async unpacks.
        return [(pkg_dir, lang, store["root"])
                for pkg_dir, lang in store["packages"]]

    async def exec_one_async(self, item: tuple) -> dict:
        pkg_dir, lang, root = item
        return await asyncio.to_thread(_dg.analyze_package, pkg_dir, lang, root)

    async def post_async(self, store: dict, prep: list,
                         profiles: list) -> str:
        store["profiles"] = profiles
        return "default"

class RenderNode(_flow.AsyncNode):
    """Per-profile render: md + json. Each render is independent; could
    be fanned out too, but `render_md` is already <10ms per crate so a
    sync loop is simpler than spinning up N threads."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "profiles": store.get("profiles", []),
            "format": store.get("format", "both"),
            "port": store.get("port", False),
        }

    async def exec_async(self, prep: dict) -> list[dict]:
        rendered: list[dict] = []
        fmt = prep["format"]
        port = prep["port"]
        for p in prep["profiles"]:
            entry: dict = {
                "stem": p.name.replace("-", "_").upper(),
            }
            if fmt in ("json", "both"):
                entry["json"] = _dg.json.dumps(p.to_json(), indent=2) + "\n"
            if fmt in ("md", "both"):
                entry["md"] = _dg.render_md(p, port=port)
            rendered.append(entry)
        return rendered

    async def post_async(self, store: dict, prep: dict,
                         rendered: list[dict]) -> str:
        store["rendered"] = rendered
        return "default"

class WriteNode(_flow.AsyncParallelBatchNode):
    """Write per-package artifacts to output_dir in parallel.
    Different files → no contention. Uses AsyncParallelBatchNode per
    the node-flow-for-multi-step iron-law."""

    async def prep_async(self, store: dict) -> list:
        # Ensure output dir exists once (here, not per-write).
        out_dir: Path = store["output_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        # Pair each render entry with the output dir so exec_one_async
        # can write without re-reading store.
        return [(entry, out_dir) for entry in store.get("rendered", [])]

    async def exec_one_async(self, item: tuple) -> list[str]:
        entry, out_dir = item
        written: list[str] = []
        stem = entry["stem"]
        if "md" in entry:
            mp = out_dir / f"{stem}.md"
            await asyncio.to_thread(mp.write_text, entry["md"])
            written.append(str(mp))
        if "json" in entry:
            jp = out_dir / f"{stem}.json"
            await asyncio.to_thread(jp.write_text, entry["json"])
            written.append(str(jp))
        return written

    async def post_async(self, store: dict, prep: list,
                         chunks: list[list[str]]) -> str:
        flat: list[str] = []
        for c in chunks:
            flat.extend(c)
        store["written"] = flat
        return "default"

class ReportNode(_flow.AsyncNode):
    """Terminal — compose summary dict for caller / stdout."""

    async def prep_async(self, store: dict) -> dict:
        return store

    async def exec_async(self, store: dict) -> dict:
        return {
            "package_count": store.get("package_count", 0),
            "files_written": len(store.get("written", [])),
            "output_dir": str(store["output_dir"]),
            "format": store.get("format", "both"),
            "first_files": store.get("written", [])[:5],
        }

    async def post_async(self, store: dict, prep: dict, report: dict) -> None:
        store["report"] = report
        return None  # terminal

class EmptyReportNode(_flow.AsyncNode):
    """Branch destination when DetectPackagesNode finds zero packages.
    Avoids running the rest of the pipeline on empty input."""

    async def prep_async(self, store: dict) -> Path:
        return store["root"]

    async def exec_async(self, root: Path) -> dict:
        return {"package_count": 0, "files_written": 0,
                "output_dir": "", "format": "", "first_files": []}

    async def post_async(self, store: dict, prep: Path, report: dict) -> None:
        store["report"] = report
        store["written"] = []
        return None

def build_docs_flow() -> _flow.AsyncFlow:
    """Construct the canonical docs-gen flow.

    Detect → [empty?] → Analyze → Render → Write → Report."""
    detect = DetectPackagesNode()
    analyze = AnalyzePackagesNode()
    render = RenderNode()
    write = WriteNode()
    report = ReportNode()
    empty = EmptyReportNode()
    f = _flow.AsyncFlow(start=detect)
    f.add_successor(detect, "default", analyze)
    f.add_successor(detect, "empty", empty)
    f.add_successor(analyze, "default", render)
    f.add_successor(render, "default", write)
    f.add_successor(write, "default", report)
    return f

def docs_scan(root: Path, output_dir: Path, *, format: str = "both",
              port: bool = False, only: Optional[set[str]] = None) -> dict:
    """Sync wrapper — drop-in for `docs_gen.cmd_scan` side effects."""
    store: dict = {
        "root": root,
        "output_dir": output_dir,
        "format": format,
        "port": port,
        "only": only,
    }
    f = build_docs_flow()
    asyncio.run(f.run_async(store))
    return store.get("report", {})

def main():
    import argparse
    p = argparse.ArgumentParser(
        prog="docs_flow.py",
        description="kaizen pocketflow docs-gen pipeline",
    )
    p.add_argument("--root", default=".")
    p.add_argument("--output", default="docs/crates/")
    p.add_argument("--format", choices=["json", "md", "both"], default="both")
    p.add_argument("--port", action="store_true")
    p.add_argument("--only", help="comma-separated package leaf names")
    p.add_argument("--timing", action="store_true")
    p.add_argument("--json", action="store_true",
                   help="emit JSON report (always last)")
    args = p.parse_args()
    root = Path(args.root).resolve()
    out_dir = Path(args.output)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    only = set(args.only.split(",")) if args.only else None
    store: dict = {
        "root": root, "output_dir": out_dir, "format": args.format,
        "port": args.port, "only": only,
    }
    f = build_docs_flow()
    asyncio.run(f.run_async(store))
    report = store["report"]
    if args.json:
        _emit(report,
              counts={"files_written": report.get("files_written", 0),
                      "packages": report.get("package_count", 0)})
    else:
        print(
            f"wrote {report['files_written']} files to {out_dir}/"
            f" ({report['package_count']} packages)",
            file=sys.stderr,
        )
    if args.timing:
        print("--- timing (ms) ---", file=sys.stderr)
        for name, ms in store.get("_timing", {}).items():
            print(f"  {name:<24} {ms} ms", file=sys.stderr)

if __name__ == "__main__":
    main()
