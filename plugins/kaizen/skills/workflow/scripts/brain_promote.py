"""kaizen brain promote — project-memory → brain promotion flow.

Walks ~/.claude/projects/<slug>/memory/ for entries that meet the
brain-promotion criteria (declared in routing.yaml::promotion):

  - ``sources_count >= 2``  — the belief / fact survived re-derivation
  - ``promote: true`` in frontmatter — explicit user opt-in

Each candidate is shown with a diff-style preview (source path,
proposed brain destination, frontmatter changes). ``--apply`` performs
the move: copy to brain, tombstone the source.

PocketFlow shape::

   ScanNode → FilterNode → PreviewNode → (--apply?) → ApplyNode → ReportNode

## CLI

::

   kaizen-brain-promote                   # list candidates (dry-run)
   kaizen-brain-promote --apply           # actually promote
   kaizen-brain-promote --filter '<glob>' # restrict by filename glob
   kaizen-brain-promote --source <project_slug>  # specific project
   kaizen-brain-promote --json
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import fnmatch
import json
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _brain  # noqa: E402
import flow as _flow  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-brain-promote", tool_version="1.0.0")


# ─── Helpers ──────────────────────────────────────────────────────────


def _all_project_memory_roots() -> list[Path]:
    """All ~/.claude/projects/*/memory/ dirs that exist."""
    base = Path("~/.claude/projects").expanduser().resolve()
    if not base.is_dir():
        return []
    out = []
    for p in base.iterdir():
        m = p / "memory"
        if m.is_dir():
            out.append(m)
    return out


def _candidate_brain_path(rec: dict, brain_root: Path) -> Path:
    """Pick a brain destination for a promoted note.

    Rules:
    - belief → Notes/pref-<slug>.md
    - world-fact → Notes/<slug>.md
    - observation → Notes/obs-<slug>.md
    - experience → Notes/<slug>.md (rare promotion case)
    """
    type_name = rec["type"]
    base_name = rec.get("brain_filename") or _brain.slugify(rec["name"] or rec["path"].split("/")[-1])
    if type_name == "belief":
        if not base_name.startswith("pref-"):
            base_name = f"pref-{base_name}"
    elif type_name == "observation":
        if not base_name.startswith("obs-"):
            base_name = f"obs-{base_name}"
    if not base_name.endswith(".md"):
        base_name = f"{base_name}.md"
    return brain_root / "Notes" / base_name


# ─── Flow nodes ──────────────────────────────────────────────────────


class ScanNode(_flow.AsyncNode):
    """Walk project-memory dir(s); read each .md file's frontmatter."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "project_slug": store.get("project_slug"),
            "filter_glob": store.get("filter_glob"),
        }

    async def exec_async(self, prep: dict) -> list:
        records = []
        if prep["project_slug"]:
            roots = [Path(f"~/.claude/projects/{prep['project_slug']}/memory").expanduser()]
        else:
            roots = _all_project_memory_roots()
        for root in roots:
            if not root.is_dir():
                continue
            for f in sorted(root.glob("*.md")):
                if f.name == "MEMORY.md":
                    continue  # the index file, not a memory entry
                if prep["filter_glob"] and not fnmatch.fnmatch(f.name, prep["filter_glob"]):
                    continue
                try:
                    text = f.read_text(encoding="utf-8")
                except OSError:
                    continue
                fm, body = _brain.parse_note(text)
                records.append({
                    "path": str(f),
                    "name": fm.get("name") or f.stem,
                    "description": fm.get("description") or "",
                    "type": fm.get("type") or "world-fact",
                    "confidence": fm.get("confidence"),
                    "sources_count": int(fm.get("sources_count") or 0),
                    "promote": bool(fm.get("promote")),
                    "fm": fm,
                    "body": body,
                })
        return records

    async def post_async(self, store: dict, prep: dict, records: list) -> str:
        store["all_records"] = records
        return "default"


class FilterNode(_flow.AsyncNode):
    """Apply the promotion criteria from routing.yaml. Only beliefs /
    world-facts are eligible (observations + experiences are already
    structurally brain-only)."""

    async def prep_async(self, store: dict) -> list:
        return store.get("all_records") or []

    async def exec_async(self, records: list) -> list:
        candidates = []
        for rec in records:
            if rec["type"] not in {"world-fact", "belief"}:
                continue
            sources_ok = rec["sources_count"] >= 2
            explicit_ok = rec["promote"]
            if not (sources_ok or explicit_ok):
                continue
            reason = []
            if sources_ok:
                reason.append(f"sources_count={rec['sources_count']}")
            if explicit_ok:
                reason.append("explicit-promote-flag")
            rec["promotion_reason"] = " + ".join(reason)
            candidates.append(rec)
        return candidates

    async def post_async(self, store: dict, _prep, candidates: list) -> str:
        store["candidates"] = candidates
        return "default"


class PreviewNode(_flow.AsyncNode):
    """Compute the proposed brain destination for each candidate. No
    writes — caller decides whether to call ApplyNode next."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "candidates": store.get("candidates") or [],
            "brain_root": store["brain_root"],
        }

    async def exec_async(self, prep: dict) -> list:
        out = []
        for rec in prep["candidates"]:
            dest = _candidate_brain_path(rec, prep["brain_root"])
            out.append({
                "source": rec["path"],
                "destination": str(dest),
                "destination_exists": dest.is_file(),
                "name": rec["name"],
                "type": rec["type"],
                "sources_count": rec["sources_count"],
                "reason": rec.get("promotion_reason", ""),
            })
        return out

    async def post_async(self, store: dict, prep: dict, previews: list) -> str:
        store["previews"] = previews
        return "default"


class ApplyNode(_flow.AsyncNode):
    """Copy source frontmatter+body into the brain destination and
    tombstone the project-memory source.

    Tombstone shape (preserves history without leaving the original
    around to drift)::

        ---
        name: <original>
        promoted_to: <KAIZEN_BRAIN_DIR>/Notes/<dest>.md
        promoted_at: <today>
        type: world-fact
        ---

        This entry was promoted to brain on <today>. See
        ``promoted_to`` for the canonical home.
    """

    async def prep_async(self, store: dict) -> dict:
        return {
            "candidates": store.get("candidates") or [],
            "brain_root": store["brain_root"],
            "apply": store.get("apply", False),
        }

    async def exec_async(self, prep: dict) -> list:
        if not prep["apply"]:
            return []
        results = []
        today = dt.date.today().isoformat()
        for rec in prep["candidates"]:
            src = Path(rec["path"])
            dst = _candidate_brain_path(rec, prep["brain_root"])
            # Build brain-side frontmatter from source
            brain_fm = dict(rec["fm"])
            brain_fm.setdefault("name", rec["name"])
            brain_fm.setdefault("description", rec["description"])
            brain_fm["type"] = rec["type"]
            brain_fm.setdefault("tags", [])
            brain_fm["sources_count"] = max(rec["sources_count"], 2)
            brain_fm.setdefault("freshness", "stable")
            brain_fm.pop("promote", None)  # consumed
            brain_fm["promoted_from"] = rec["path"]
            brain_fm["promoted_at"] = today
            _brain.write_note(dst, brain_fm, rec["body"])
            # Tombstone the source
            tomb_fm = {
                "name": rec["name"],
                "description": f"Promoted to brain on {today}",
                "type": rec["type"],
                "promoted_to": str(dst),
                "promoted_at": today,
            }
            tomb_body = (
                f"# {rec['name']}\n\n"
                f"This entry was promoted to brain on {today}.\n"
                f"Canonical home: `{dst}`\n"
            )
            _brain.write_note(src, tomb_fm, tomb_body)
            results.append({"source": str(src), "destination": str(dst)})
        return results

    async def post_async(self, store: dict, _prep, results: list) -> str:
        store["applied"] = results
        return "default"


class ReportNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> None:
        return None

    async def exec_async(self, prep) -> None:
        return None

    async def post_async(self, store: dict, _prep, _exec) -> str:
        store["report"] = {
            "candidates": store.get("previews") or [],
            "applied": store.get("applied") or [],
            "total_candidates": len(store.get("previews") or []),
            "total_applied": len(store.get("applied") or []),
        }
        return "default"


def build_promote_flow() -> _flow.AsyncFlow:
    scan = ScanNode()
    filt = FilterNode()
    preview = PreviewNode()
    apply = ApplyNode()
    report = ReportNode()
    f = _flow.AsyncFlow(scan)
    f.add_successor(scan, "default", filt)
    f.add_successor(filt, "default", preview)
    f.add_successor(preview, "default", apply)
    f.add_successor(apply, "default", report)
    return f


def promote(
    *,
    project_slug: Optional[str] = None,
    filter_glob: Optional[str] = None,
    apply: bool = False,
    brain_root: Optional[Path] = None,
) -> dict:
    """Sync helper. Returns the report dict."""
    return asyncio.run(_promote_async(
        project_slug=project_slug,
        filter_glob=filter_glob,
        apply=apply,
        brain_root=brain_root,
    ))


async def _promote_async(**kwargs) -> dict:
    store: dict = {
        "project_slug": kwargs.get("project_slug"),
        "filter_glob": kwargs.get("filter_glob"),
        "apply": kwargs.get("apply", False),
        "brain_root": kwargs.get("brain_root") or _brain.brain_root(),
    }
    await build_promote_flow().run_async(store)
    return store.get("report") or {}


# ─── CLI ─────────────────────────────────────────────────────────────


def _cmd_run(args) -> int:
    report = promote(
        project_slug=args.source,
        filter_glob=args.filter,
        apply=args.apply,
    )
    if args.json:
        _emit(report)
        return 0
    if not report.get("candidates"):
        print("[kaizen-brain-promote] no candidates — nothing meets the threshold")
        return 0
    print(f"[kaizen-brain-promote] {report['total_candidates']} candidate(s)")
    print()
    for c in report["candidates"]:
        exists = "(would overwrite)" if c["destination_exists"] else "(would create)"
        if args.apply:
            exists = "(overwrote)" if c["destination_exists"] else "(created)"
        print(f"  {c['type']:<12} {c['name']}")
        print(f"    {c['source']}")
        print(f"    -> {c['destination']}  {exists}")
        print(f"    reason: {c['reason']}")
        print()
    if not args.apply:
        print("dry-run — re-run with --apply to promote.")
    else:
        print(f"applied {report['total_applied']} promotion(s).")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-brain-promote",
        description="Promote project-memory entries to brain (Notes/).",
    )
    p.add_argument("--source", help="restrict to one project slug")
    p.add_argument("--filter", help="filename glob filter (e.g. 'feedback_*.md')")
    p.add_argument("--apply", action="store_true", help="actually move files")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_run)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
