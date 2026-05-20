# consolidated-cli-parent: brain

"""kaizen brain rank — score-based Top Beliefs auto-ranker.

Port of upstream ``remember-md/remember/scripts/promote.js``. Walks
``Notes/*.md``, filters by ``type=belief`` + confidence + sources +
freshness thresholds, ranks by ``confidence * log(sources_count + 1)``,
and REPLACES ``Persona.md ## Top Beliefs`` with the top-N.

Distinct from ``brain.py::_cmd_promote_belief`` (manual single-note
append at ``rank=max+1``). This module is the **automated** path —
section gets fully rewritten so low-score Notes get demoted.

## Bootstrap mode

When ``beliefs_count < bootstrap_max_beliefs`` (default 20), relaxed
thresholds apply (conf >= 0.7, sources >= 1). Bootstrap takes the
**more permissive** value per-field, so a user who explicitly
relaxed thresholds in their config keeps their setting. Disable
entirely with ``bootstrap: false`` in the evolution config.

## CLI

::

   kaizen-brain-rank                   # rerun + write
   kaizen-brain-rank --dry-run         # preview deltas only
   kaizen-brain-rank --brain PATH      # alternate brain root
   kaizen-brain-rank --json            # structured envelope
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent))  # for evolution_log
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))

import _brain  # noqa: E402

# ─── Thresholds ──────────────────────────────────────────────────────


DEFAULT_THRESHOLDS = {
    "promotion_confidence": 0.85,
    "promotion_sources": 5,
    "stale_days": 90,
    "consolidate_touches": 5,
    "top_beliefs_n": 10,
}

# Cold-start: relaxed thresholds applied when total beliefs in the brain
# are below ``bootstrap_max_beliefs``. Without this, a fresh brain never
# has anything in Persona ## Top Beliefs because reaching 5 sources at
# 0.85 confidence on a single belief takes weeks of disciplined capture.
BOOTSTRAP_THRESHOLDS = {
    "promotion_confidence": 0.7,
    "promotion_sources": 1,
    "bootstrap_max_beliefs": 20,
}

ELIGIBLE_FRESHNESS = frozenset({"stable", "strengthening", "fresh"})

TOP_BELIEFS_HEADING = "## Top Beliefs"

# ─── Pure functions ──────────────────────────────────────────────────


def score(rec: dict) -> float:
    """Score a belief: confidence × log(sources_count + 1). Mirrors
    upstream promote.js::score. The +1 prevents log(0); the log
    dampens runaway growth from one extremely well-sourced belief."""
    return float(rec["confidence"]) * math.log(int(rec["sources_count"]) + 1)


def filter_candidates(beliefs: list[dict], thresholds: dict) -> list[dict]:
    """Gate by confidence + sources + freshness. Mirrors
    upstream promote.js::filterCandidates."""
    return [
        b for b in beliefs
        if float(b["confidence"]) >= thresholds["promotion_confidence"]
        and int(b["sources_count"]) >= thresholds["promotion_sources"]
        and b.get("freshness", "stable") in ELIGIBLE_FRESHNESS
    ]


def rank_and_take(candidates: list[dict], n: int) -> list[dict]:
    """Sort by score (desc), take top-N. Mirrors
    upstream promote.js::rankAndTake."""
    return sorted(candidates, key=score, reverse=True)[:n]


def effective_thresholds(beliefs_count: int, config: dict) -> tuple[dict, bool]:
    """Pick (thresholds, bootstrap) tuple. Mirrors
    upstream promote.js::effectiveThresholds.

    ``config`` shape: ``{"thresholds": {...}, "bootstrap": true|false}``.
    Returns ``(thresholds_dict, is_bootstrap_active)``."""
    cfg = config["thresholds"]
    if config.get("bootstrap") is False:
        return cfg, False
    if beliefs_count >= BOOTSTRAP_THRESHOLDS["bootstrap_max_beliefs"]:
        return cfg, False
    return {
        **cfg,
        "promotion_confidence": min(
            float(cfg["promotion_confidence"]),
            BOOTSTRAP_THRESHOLDS["promotion_confidence"],
        ),
        "promotion_sources": min(
            int(cfg["promotion_sources"]),
            BOOTSTRAP_THRESHOLDS["promotion_sources"],
        ),
    }, True


def find_beliefs(brain_root: Path) -> list[dict]:
    """Walk Notes/, return list of belief records.

    Each record: ``{path, title, confidence, sources_count, freshness}``.
    Mirrors upstream promote.js::findBeliefs."""
    notes_dir = brain_root / "Notes"
    if not notes_dir.is_dir():
        return []
    out = []
    for f in sorted(notes_dir.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _body = _brain.parse_note(text)
        if fm.get("type") != "belief":
            continue
        conf = fm.get("confidence")
        if conf is None:
            continue
        try:
            conf_f = float(conf)
        except (TypeError, ValueError):
            continue
        out.append({
            "path": f"Notes/{f.name}",
            "title": fm.get("name") or f.stem,
            "confidence": conf_f,
            "sources_count": int(fm.get("sources_count") or 0),
            "freshness": fm.get("freshness") or "stable",
        })
    return out


def render_top_beliefs_section(
    top: list[dict],
    *,
    bootstrap: bool = False,
    beliefs_count: int = 0,
    thresholds: Optional[dict] = None,
) -> str:
    """Render the ## Top Beliefs section body (heading + entries).

    Empty top produces a placeholder line citing the thresholds.
    Mirrors upstream promote.js::renderTopBeliefsSection."""
    if not top:
        conf = thresholds["promotion_confidence"] if thresholds else 0.85
        src = thresholds["promotion_sources"] if thresholds else 5
        mode = " (bootstrap mode)" if bootstrap else ""
        return (
            f"{TOP_BELIEFS_HEADING}\n\n"
            f"_None yet — need beliefs with conf>={conf} and sources>={src}{mode}. "
            f"Currently {beliefs_count} belief(s) in brain._\n"
        )
    lines = [
        f"{i + 1}. [[{b['path']}]] — "
        f"conf={float(b['confidence']):.2f} "
        f"sources={int(b['sources_count'])} "
        f"freshness={b.get('freshness', 'stable')}"
        for i, b in enumerate(top)
    ]
    return f"{TOP_BELIEFS_HEADING}\n\n" + "\n".join(lines) + "\n"


def compute_deltas(current_links: list[str], top: list[dict]) -> dict:
    """Diff existing Top Beliefs vs new top-N. Mirrors
    upstream promote.js::computeDeltas.

    Returns ``{promoted: [recs new to top], demoted: [paths dropped]}``."""
    top_paths = {t["path"] for t in top}
    promoted = [t for t in top if t["path"] not in current_links]
    demoted = [link for link in current_links if link not in top_paths]
    return {"promoted": promoted, "demoted": demoted}


def read_current_top_beliefs(persona_path: Path) -> list[str]:
    """Pull the ``[[link]]`` text from the existing ## Top Beliefs block.

    Strips trailing ``.md`` from refs so the output matches the
    ``path`` field shape used in ranked records (``Notes/x.md``).
    Actually returns the link AS WRITTEN in the persona (could be
    ``Notes/x`` or ``Notes/x.md``). compute_deltas handles both
    by passing raw strings."""
    if not persona_path.is_file():
        return []
    text = persona_path.read_text(encoding="utf-8")
    in_section = False
    links: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if in_section:
                break
            if line.strip() == TOP_BELIEFS_HEADING:
                in_section = True
            continue
        if not in_section:
            continue
        m = re.search(r"\[\[([^\]]+)\]\]", line)
        if m:
            links.append(m.group(1))
    return links


def write_top_beliefs(persona_path: Path, top: list[dict], **opts) -> None:
    """Replace the ## Top Beliefs section atomically.

    Unlike ``brain.py::_cmd_promote_belief`` which appends one entry,
    this REPLACES the whole block — so demoted entries disappear.

    Mirrors upstream promote.js::writeTopBeliefs (atomic via
    tempfile-then-rename)."""
    text = persona_path.read_text(encoding="utf-8") if persona_path.is_file() else ""
    new_section = render_top_beliefs_section(top, **opts)

    heading_re = re.compile(r"^## Top Beliefs[ \t]*$", re.M)
    m = heading_re.search(text)
    if m:
        start = m.start()
        after = text[m.end():]
        next_h = re.search(r"^## ", after, re.M)
        if next_h:
            end = m.end() + next_h.start()
            text = text[:start] + new_section + "\n" + text[end:]
        else:
            text = text[:start] + new_section
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n" + new_section

    # Atomic write: tempfile + rename.
    tmp = persona_path.with_suffix(persona_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(persona_path)


# ─── Config loader ───────────────────────────────────────────────────


def _evolution_config_path() -> Path:
    """Path to user's evolution-config override file. Diverges from
    upstream ``~/.local/state/remember/config.json`` — kaizen uses
    ``$KAIZEN_EVOLUTION_CONFIG`` env, else
    ``$KAIZEN_BRAIN_DIR/evolution.json``."""
    env = os.environ.get("KAIZEN_EVOLUTION_CONFIG")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return _brain.brain_root() / "evolution.json"


def load_evolution_config() -> dict:
    """Load user threshold overrides + auto_promote flag.

    Shape::

       {
         "thresholds": {...},     # merged onto DEFAULT_THRESHOLDS
         "auto_promote": bool,    # default True
         "bootstrap": bool,       # default True
       }

    Mirrors upstream config.js::loadEvolutionConfig (path differs)."""
    p = _evolution_config_path()
    user: dict = {}
    if p.is_file():
        try:
            user = json.loads(p.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            user = {}
    if not isinstance(user, dict):
        user = {}
    return {
        "thresholds": {**DEFAULT_THRESHOLDS, **(user.get("thresholds") or {})},
        "auto_promote": (
            bool(user["auto_promote"]) if isinstance(user.get("auto_promote"), bool) else True
        ),
        "bootstrap": (
            bool(user["bootstrap"]) if isinstance(user.get("bootstrap"), bool) else True
        ),
        "paths": user.get("paths") or {},
    }


# ─── Orchestration ───────────────────────────────────────────────────


def run(
    brain: Optional[Path] = None,
    *,
    dry_run: bool = False,
    config_override: Optional[dict] = None,
    log_path: Optional[Path] = None,
) -> dict:
    """Find + filter + rank + (write).

    Returns::

       {
         "top": list[record],          # final top-N
         "promoted": list[record],     # new entries
         "demoted": list[str],         # dropped link strings
         "beliefs_count": int,
         "candidates_count": int,
         "wrote": bool,
         "bootstrap": bool,
         "effective_thresholds": dict,
       }

    Side effects: when ``not dry_run and config.auto_promote and
    Persona.md exists``, rewrites the ## Top Beliefs section AND
    appends PROMOTE/DEMOTE events to evolution.log."""
    brain_root = brain or _brain.brain_root()
    persona_path = brain_root / "Persona.md"
    config = config_override or load_evolution_config()

    beliefs = find_beliefs(brain_root)
    effective, bootstrap = effective_thresholds(len(beliefs), config)
    candidates = filter_candidates(beliefs, effective)
    top = rank_and_take(candidates, int(effective.get("top_beliefs_n", 10)))
    current_links = read_current_top_beliefs(persona_path)
    deltas = compute_deltas(current_links, top)

    will_write = bool(
        not dry_run and config.get("auto_promote", True) and persona_path.is_file()
    )

    if will_write:
        write_top_beliefs(
            persona_path, top,
            bootstrap=bootstrap,
            beliefs_count=len(beliefs),
            thresholds=effective,
        )
        # Append PROMOTE/DEMOTE events to evolution.log.
        try:
            import evolution_log as _ev
            tag = " [bootstrap]" if bootstrap else ""
            for p in deltas["promoted"]:
                _ev.append_event(
                    "PROMOTE",
                    f"{p['path']} → Persona.Top "
                    f"conf={float(p['confidence']):.2f} "
                    f"sources={int(p['sources_count'])}{tag}",
                    log_path=log_path,
                )
            for d in deltas["demoted"]:
                _ev.append_event(
                    "DEMOTE",
                    f"{d} ← Persona.Top reason=below_threshold{tag}",
                    log_path=log_path,
                )
        except (ImportError, ValueError, OSError):
            pass  # evolution log is best-effort; don't fail the rank

    return {
        "top": top,
        "promoted": deltas["promoted"],
        "demoted": deltas["demoted"],
        "beliefs_count": len(beliefs),
        "candidates_count": len(candidates),
        "wrote": will_write,
        "bootstrap": bootstrap,
        "effective_thresholds": effective,
    }


# ─── CLI ─────────────────────────────────────────────────────────────


def _emit_json(result: dict) -> None:
    """Emit a structured envelope mirroring kaizen conventions."""
    sys.stdout.write(json.dumps({
        "data": result,
        "kaizen": {
            "command": "brain_rank.py",
            "tool": "kaizen-brain-rank",
            "tool_version": "1.0.0",
            "schema_version": 1,
        },
    }, default=str, indent=2) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kaizen-brain-rank",
        description="Score-rank beliefs + rewrite Persona ## Top Beliefs.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="preview deltas without writing")
    ap.add_argument("--brain", type=Path, default=None,
                    help="brain root path (default: $KAIZEN_BRAIN_DIR)")
    ap.add_argument("--json", action="store_true",
                    help="emit structured envelope on stdout")
    args = ap.parse_args(argv)

    if os.environ.get("KAIZEN_BRAIN_RANK_DISABLE") == "1":
        sys.stderr.write("kaizen-brain-rank: disabled via KAIZEN_BRAIN_RANK_DISABLE=1\n")
        return 0

    result = run(args.brain, dry_run=args.dry_run)

    if args.json:
        _emit_json(result)
        return 0

    sys.stdout.write(f"Beliefs: {result['beliefs_count']}\n")
    sys.stdout.write(
        f"Mode: {'bootstrap (relaxed thresholds)' if result['bootstrap'] else 'normal'}\n"
    )
    eff = result["effective_thresholds"]
    sys.stdout.write(
        f"Thresholds: conf>={eff['promotion_confidence']} "
        f"sources>={eff['promotion_sources']}\n"
    )
    sys.stdout.write(f"Above threshold: {result['candidates_count']}\n")
    sys.stdout.write(f"Top: {len(result['top'])}\n")
    sys.stdout.write(f"Promoted: {len(result['promoted'])}\n")
    sys.stdout.write(f"Demoted: {len(result['demoted'])}\n")
    if args.dry_run:
        sys.stdout.write("(dry run — no changes written)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
