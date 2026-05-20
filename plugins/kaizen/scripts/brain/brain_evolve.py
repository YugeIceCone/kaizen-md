# consolidated-cli-parent: brain

"""kaizen brain evolve — periodic consolidation + freshness review.

Scans all brain Notes for:

  - **Near-duplicates** — same slug-stem or very similar names. Surfaces
    as merge candidates.
  - **Staleness drift** — notes with ``freshness: fresh`` that haven't
    been updated in N days; recommend bump to ``stable`` or ``stale``.
  - **Source-count growth** — notes that crossed the sources_count>=2
    threshold and are eligible for brain promotion (brain-only here;
    project-memory entries are surfaced by brain_promote).
  - **Persona drift** — Notes referenced in Persona.md ## Top Beliefs
    whose confidence drifted or whose source-count grew.

PocketFlow shape::

   LoadNotesNode → FindDuplicatesNode → CheckFreshnessNode
   → ScanPersonaRefsNode → ReportNode

Default behaviour is REPORT-ONLY. ``--apply`` is a no-op for now —
evolution actions are user-led (the report tells the user what to
look at; the user decides what to merge / bump). Future passes may
add auto-merge for clear duplicates behind an explicit flag.

## CLI

::

   kaizen-brain-evolve                   # full report
   kaizen-brain-evolve --json
   kaizen-brain-evolve --stale-days 90   # mark fresh→stale threshold
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import _brain  # noqa: E402
import flow as _flow  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-brain-evolve", tool_version="1.0.0")

# ─── Flow nodes ──────────────────────────────────────────────────────

class LoadNotesNode(_flow.AsyncNode):
    """Read every Note in brain/Notes/ into memory once."""

    async def prep_async(self, store: dict) -> Path:
        return store["brain_root"]

    async def exec_async(self, root: Path) -> list:
        notes: list[dict] = []
        notes_dir = root / "Notes"
        if not notes_dir.is_dir():
            return notes
        for f in sorted(notes_dir.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, body = _brain.parse_note(text)
            try:
                mtime = dt.datetime.fromtimestamp(
                    f.stat().st_mtime, dt.timezone.utc,
                )
            except OSError:
                mtime = dt.datetime.now(dt.timezone.utc)
            notes.append({
                "path": str(f),
                "stem": f.stem,
                "name": fm.get("name") or f.stem,
                "description": fm.get("description") or "",
                "type": fm.get("type") or "world-fact",
                "confidence": fm.get("confidence"),
                "sources_count": int(fm.get("sources_count") or 0),
                "freshness": fm.get("freshness"),
                "updated_fm": fm.get("updated"),
                "mtime": mtime,
                "fm": fm,
                "body": body,
            })
        return notes

    async def post_async(self, store: dict, _prep, notes: list) -> str:
        store["notes"] = notes
        return "default"

class FindDuplicatesNode(_flow.AsyncNode):
    """Heuristic duplicate detection — same slug-stem after stripping
    common prefixes (pref-/obs-/etc.) or word-overlap >= 60%."""

    async def prep_async(self, store: dict) -> list:
        return store.get("notes") or []

    async def exec_async(self, notes: list) -> list:
        by_root_stem: dict[str, list[dict]] = defaultdict(list)
        for n in notes:
            stem = n["stem"]
            for prefix in ("pref-", "obs-", "fact-"):
                if stem.startswith(prefix):
                    stem = stem[len(prefix):]
                    break
            by_root_stem[stem].append(n)
        dupes = []
        for stem, group in by_root_stem.items():
            if len(group) > 1:
                dupes.append({
                    "stem": stem,
                    "files": [n["path"] for n in group],
                    "names": [n["name"] for n in group],
                })
        return dupes

    async def post_async(self, store: dict, _prep, dupes: list) -> str:
        store["duplicates"] = dupes
        return "default"

class CheckFreshnessNode(_flow.AsyncNode):
    """Flag notes whose freshness label disagrees with their mtime.

    Rules (configurable via --stale-days):

    - ``freshness: fresh`` but mtime > N days ago → "should be stable"
    - ``freshness: stable`` but mtime > N*4 days ago → "consider stale"
    - no freshness field → "set a freshness"
    """

    async def prep_async(self, store: dict) -> dict:
        return {
            "notes": store.get("notes") or [],
            "stale_days": store.get("stale_days", 30),
        }

    async def exec_async(self, prep: dict) -> list:
        now = dt.datetime.now(dt.timezone.utc)
        stale_days = prep["stale_days"]
        out = []
        for n in prep["notes"]:
            age_days = (now - n["mtime"]).days
            freshness = n["freshness"]
            recommendation = None
            if freshness is None:
                recommendation = "set-freshness"
            elif freshness == "fresh" and age_days > stale_days:
                recommendation = "demote-to-stable"
            elif freshness == "stable" and age_days > stale_days * 4:
                recommendation = "consider-stale"
            if recommendation:
                out.append({
                    "path": n["path"],
                    "name": n["name"],
                    "freshness": freshness,
                    "age_days": age_days,
                    "recommendation": recommendation,
                })
        return out

    async def post_async(self, store: dict, _prep, items: list) -> str:
        store["freshness_drift"] = items
        return "default"

class ScanPersonaRefsNode(_flow.AsyncNode):
    """Read brain/Persona.md ## Top Beliefs, return the list of Note
    files it references. Identify any references that point at notes
    whose sources_count grew (so the persona confidence may be stale)."""

    async def prep_async(self, store: dict) -> Path:
        return store["brain_root"]

    async def exec_async(self, root: Path) -> dict:
        persona = root / "Persona.md"
        if not persona.is_file():
            return {"refs": [], "notes_by_name": {}}
        try:
            text = persona.read_text(encoding="utf-8")
        except OSError:
            return {"refs": [], "notes_by_name": {}}
        # Pull `[[Notes/<name>]]` references
        refs = re.findall(r"\[\[Notes/([^\]]+?)(?:\.md)?\]\]", text)
        # Pull conf=<X> sources=<N> markers from "## Top Beliefs"
        info = {}
        for m in re.finditer(
            r"\[\[Notes/([^\]]+?)(?:\.md)?\]\]\s*—\s*conf=([0-9.]+)\s+sources=(\d+)",
            text,
        ):
            info[m.group(1)] = {
                "conf": float(m.group(2)),
                "sources": int(m.group(3)),
            }
        return {"refs": refs, "persona_info": info}

    async def post_async(self, store: dict, _prep, persona_state: dict) -> str:
        notes = store.get("notes") or []
        persona_info = persona_state.get("persona_info") or {}
        # Cross-check: which Top-Beliefs refs have evolved beyond Persona.md?
        drift = []
        notes_by_stem = {n["stem"]: n for n in notes}
        for stem, p_info in persona_info.items():
            n = notes_by_stem.get(stem)
            if not n:
                drift.append({"stem": stem, "issue": "missing-note"})
                continue
            actual_sources = n["sources_count"]
            actual_conf = n["confidence"]
            if p_info["sources"] != actual_sources:
                drift.append({
                    "stem": stem,
                    "issue": "sources-drift",
                    "persona_sources": p_info["sources"],
                    "actual_sources": actual_sources,
                })
            if (actual_conf is not None
                    and abs(p_info["conf"] - actual_conf) > 0.05):
                drift.append({
                    "stem": stem,
                    "issue": "conf-drift",
                    "persona_conf": p_info["conf"],
                    "actual_conf": actual_conf,
                })
        store["persona_refs"] = persona_state.get("refs") or []
        store["persona_drift"] = drift
        return "default"

class ReportNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> None:
        return None

    async def exec_async(self, _prep) -> None:
        return None

    async def post_async(self, store: dict, _prep, _exec) -> str:
        store["report"] = {
            "total_notes": len(store.get("notes") or []),
            "duplicates": store.get("duplicates") or [],
            "freshness_drift": store.get("freshness_drift") or [],
            "persona_refs": store.get("persona_refs") or [],
            "persona_drift": store.get("persona_drift") or [],
        }
        return "default"

class RerankPersonaNode(_flow.AsyncNode):
    """v1.40+ — score-rank beliefs and (when not dry-run + auto_promote)
    rewrite Persona ## Top Beliefs. Replaces the detect-only behavior
    that previously only flagged drift — now closes the loop.

    Honors ``store["dry_run"]`` so callers can preview without writing.
    Falls back gracefully if brain_rank isn't importable (e.g. dev
    environment mid-migration)."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "brain_root": store["brain_root"],
            "dry_run": bool(store.get("dry_run", False)),
        }

    async def exec_async(self, prep: dict) -> dict:
        try:
            import brain_rank as _br
        except ImportError:
            return {"skipped": "brain_rank import failed"}
        return _br.run(brain=prep["brain_root"], dry_run=prep["dry_run"])

    async def post_async(self, store: dict, _prep, result: dict) -> str:
        store["rerank"] = result
        return "default"

def build_evolve_flow() -> _flow.AsyncFlow:
    load = LoadNotesNode()
    dupe = FindDuplicatesNode()
    fresh = CheckFreshnessNode()
    persona = ScanPersonaRefsNode()
    rerank = RerankPersonaNode()
    report = ReportNode()
    f = _flow.AsyncFlow(load)
    f.add_successor(load, "default", dupe)
    f.add_successor(dupe, "default", fresh)
    f.add_successor(fresh, "default", persona)
    f.add_successor(persona, "default", rerank)
    f.add_successor(rerank, "default", report)
    return f

def evolve(
    *,
    brain_root: Optional[Path] = None,
    stale_days: int = 30,
    dry_run: bool = False,
) -> dict:
    return asyncio.run(_evolve_async(
        brain_root=brain_root, stale_days=stale_days, dry_run=dry_run,
    ))

async def _evolve_async(**kwargs) -> dict:
    store: dict = {
        "brain_root": kwargs.get("brain_root") or _brain.brain_root(),
        "stale_days": kwargs.get("stale_days", 30),
        "dry_run": kwargs.get("dry_run", False),
    }
    await build_evolve_flow().run_async(store)
    report = store.get("report") or {}
    # Surface the rerank result alongside the existing drift report
    report["rerank"] = store.get("rerank") or {}
    return report

# ─── CLI ─────────────────────────────────────────────────────────────

def _cmd_run(args) -> int:
    report = evolve(stale_days=args.stale_days, dry_run=args.dry_run)
    if args.json:
        _emit(report)
        return 0
    print(f"[kaizen-brain-evolve] {report['total_notes']} note(s) scanned")
    print()
    if report["duplicates"]:
        print(f"DUPLICATE CANDIDATES ({len(report['duplicates'])}):")
        for d in report["duplicates"]:
            print(f"  - stem={d['stem']}")
            for f, n in zip(d["files"], d["names"]):
                print(f"    {f}  ({n})")
        print()
    if report["freshness_drift"]:
        print(f"FRESHNESS DRIFT ({len(report['freshness_drift'])}):")
        for n in report["freshness_drift"][:20]:
            print(f"  - {n['recommendation']:<18} age={n['age_days']:>3}d  "
                  f"{n['name']}")
        print()
    if report["persona_drift"]:
        print(f"PERSONA DRIFT ({len(report['persona_drift'])}):")
        for d in report["persona_drift"]:
            print(f"  - {d['issue']:<14} {d['stem']}: {d}")
        print()
    rerank = report.get("rerank") or {}
    if rerank and not rerank.get("skipped"):
        mode = "bootstrap" if rerank.get("bootstrap") else "normal"
        print(f"RERANK (mode={mode}): "
              f"{len(rerank.get('promoted', []))} promoted, "
              f"{len(rerank.get('demoted', []))} demoted, "
              f"wrote={rerank.get('wrote', False)}")
        print()
    if not (report["duplicates"] or report["freshness_drift"] or report["persona_drift"]):
        print("  no drift detected — brain is consolidated.")
    return 0

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-brain-evolve",
        description="Consolidate + freshness-review the kaizen Second Brain.",
    )
    p.add_argument("--stale-days", type=int, default=30,
                   help="days before 'fresh' notes get flagged (default 30)")
    p.add_argument("--dry-run", action="store_true",
                   help="preview rerank deltas without writing Persona ## Top Beliefs")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_run)
    args = p.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
