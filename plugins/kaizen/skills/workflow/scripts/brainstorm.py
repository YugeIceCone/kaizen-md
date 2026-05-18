#!/usr/bin/env python3
"""kaizen-brainstorm — typed contract for brainstorming JSONL output.

Public surface:

    _compute_idea_signals(draft) -> dict
        Pure fn — maps an idea-draft dict to the signals dict the
        brainstorm-rubric.yaml walks. Mirrors handoff exemplar.

    score_jsonl(rows, rubric_path) -> list[dict]
        Enrich each row with auto_bucket / classification_confidence /
        rationale / rubric_version. Preserves any existing
        manual_bucket.

    run_override_loop(rows, *, ask_user_question=None)
        Surfaces NEEDS_AGENT rows for manual bucketing (added in P6).

    should_emit_jsonl(idea_count, *, threshold=10)
        Threshold-gate helper for the SKILL agent loop (added in P7).

    main([argv]) -> int
        argparse entry — `score` subcommand for v1.

CLI: `kaizen-brainstorm score --input PATH --rubric PATH [--rewrite] [--force]
                              [--max-ideas N] [--json]`
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402
import schema_cli  # noqa: E402
from _atomic import atomic_write  # noqa: E402

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover — installed in kaizen environments
    sys.stderr.write("kaizen-brainstorm: PyYAML required\n")
    raise

_TRIGGER_RE = re.compile(r"\bwhen\b|\btrigger\b|→|\bif\b.*\bthen\b", re.I)
_DEFAULT_MAX_IDEAS = 250
_DEFAULT_THRESHOLD = 10
_emit = _envelope.emitter("kaizen-brainstorm", tool_version="1.0.0")


def should_emit_jsonl(idea_count: int, *, threshold: int = _DEFAULT_THRESHOLD) -> bool:
    """True when brainstorm has > threshold ideas (default 10).

    Pure fn. Empty brainstorms (0 ideas) always return False (no-op,
    not an error). Under-threshold means prose-only narration."""
    return idea_count > threshold


# ─── Pure-fn signal computer ─────────────────────────────────────────


def _compute_idea_signals(draft: dict) -> dict:
    """Map an idea-draft to the signals dict walked by brainstorm-rubric.yaml.

    Pure: no I/O, no env, no clock. Same input → same output. Does
    not mutate `draft`. Mirrors brainstorm-rubric.yaml `signal:` keys
    one-for-one (named-once discipline from decision-rubric Iron Laws).
    """
    text = draft.get("idea", "") or ""
    return {
        "length_words":    len(text.split()),
        "has_tool_dep":    bool(draft.get("tools")),
        "trigger_present": bool(_TRIGGER_RE.search(text)),
        "effort_bucket":   draft.get("effort_estimate", "M") or "M",
        "yagni_flag":      bool(draft.get("yagni", False)),
        "radical_flag":    bool(draft.get("radical", False)),
        "llm_confidence":  float(draft.get("confidence", 0.5) or 0.5),
        "novelty_score":   float(draft.get("novelty_score", 0.5) or 0.5),
    }


# ─── JSONL I/O + rubric version ──────────────────────────────────────


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {i}: invalid JSON: {exc}") from exc
    return rows


def _rubric_version(rubric_path: Path) -> str:
    """Read top-level `version:` from the rubric YAML (string)."""
    with rubric_path.open("r", encoding="utf-8") as f:
        raw = _yaml.safe_load(f) or {}
    return str(raw.get("version", "1"))


# ─── Rubric application ──────────────────────────────────────────────


def score_jsonl(rows: list[dict], rubric_path: Path) -> list[dict]:
    """Enrich each row with auto_bucket / classification_confidence /
    rationale / rubric_version. Existing manual_bucket preserved."""
    walker = schema_cli.BucketWalker.from_yaml(rubric_path)
    rv = _rubric_version(rubric_path)
    out: list[dict] = []
    for row in rows:
        signals = _compute_idea_signals(row)
        try:
            result = walker.evaluate(signals)
            auto_bucket = result.bucket
            confidence = float(result.confidence)
            rationale = result.rationale
        except Exception as exc:  # defensive
            auto_bucket = "NEEDS_AGENT"
            confidence = 0.0
            rationale = f"signal computer / rubric failed: {exc}"
        enriched = dict(row)
        enriched["auto_bucket"] = auto_bucket
        enriched["classification_confidence"] = confidence
        enriched["rationale"] = rationale
        enriched["rubric_version"] = rv
        out.append(enriched)
    return out


# ─── override loop ───────────────────────────────────────────────────


def run_override_loop(rows: list[dict],
                       *, ask_user_question=None) -> list[dict]:
    """Surface NEEDS_AGENT rows for manual bucketing.

    `ask_user_question` is the injection point — the production code
    plugs in the actual AskUserQuestion call; tests mock it to a fn
    that returns a {id_str: bucket_str} dict.

    Scripted runs set KAIZEN_BRAINSTORM_BATCH=1 to skip the prompt
    — NEEDS_AGENT rows pass through with manual_bucket unset.
    """
    if os.environ.get("KAIZEN_BRAINSTORM_BATCH") == "1":
        needs = sum(1 for r in rows if r.get("auto_bucket") == "NEEDS_AGENT")
        if needs:
            sys.stderr.write(
                f"[kaizen-brainstorm] BATCH=1: {needs} NEEDS_AGENT rows "
                f"left without manual_bucket\n"
            )
        return rows
    needs_agent = [r for r in rows if r.get("auto_bucket") == "NEEDS_AGENT"]
    if not needs_agent or ask_user_question is None:
        return rows
    picks = ask_user_question(needs_agent) or {}
    out: list[dict] = []
    for r in rows:
        rid = str(r.get("id"))
        if rid in picks:
            r = dict(r)
            r["manual_bucket"] = picks[rid]
        out.append(r)
    return out


# ─── score subcommand ────────────────────────────────────────────────


def _cmd_score(args) -> int:
    inp = Path(args.input).expanduser()
    rubric = Path(args.rubric).expanduser()

    if not inp.is_file():
        sys.stderr.write(f"[kaizen-brainstorm score] input not found: {inp}\n")
        _emit({"input": str(inp), "errors": ["input not found"]}, verdict="red")
        return 1
    if not rubric.is_file():
        sys.stderr.write(f"[kaizen-brainstorm score] rubric not found: {rubric}\n")
        _emit({"rubric": str(rubric), "errors": ["rubric not found"]}, verdict="red")
        return 1

    max_ideas = int(os.environ.get("KAIZEN_BRAINSTORM_MAX_IDEAS",
                                    args.max_ideas or _DEFAULT_MAX_IDEAS))

    try:
        rows = _load_jsonl(inp)
    except ValueError as exc:
        _emit({"input": str(inp), "errors": [str(exc)]}, verdict="red")
        return 1

    if len(rows) > max_ideas:
        _emit({"input": str(inp), "count": len(rows), "max_ideas": max_ideas,
                "errors": [f"{len(rows)} ideas > max_ideas {max_ideas}"]},
              verdict="red")
        return 1

    if not rows:
        sys.stderr.write("[kaizen-brainstorm score] no ideas to score\n")
        _emit({"input": str(inp), "rows": [], "count": 0,
                "buckets": {}, "rubric_version": _rubric_version(rubric)},
              verdict="green")
        return 0

    # rubric-version drift check on --rewrite
    rv = _rubric_version(rubric)
    if args.rewrite and not args.force:
        drift_ids = [r.get("id") for r in rows
                     if "rubric_version" in r and str(r["rubric_version"]) != rv]
        if drift_ids:
            sys.stderr.write(
                f"[kaizen-brainstorm score] rubric_version drift "
                f"(current={rv}, drifting rows={drift_ids[:5]}"
                f"{'...' if len(drift_ids) > 5 else ''}) "
                f"— re-run with --force to overwrite\n"
            )
            return 2

    enriched = score_jsonl(rows, rubric)

    if args.rewrite:
        body = "\n".join(json.dumps(r, sort_keys=True) for r in enriched) + "\n"
        atomic_write(inp, body)

    bucket_counts: dict[str, int] = {}
    for r in enriched:
        bucket_counts[r["auto_bucket"]] = bucket_counts.get(r["auto_bucket"], 0) + 1

    _emit(
        {"input": str(inp), "rubric": str(rubric), "rows": enriched,
         "count": len(enriched), "buckets": bucket_counts,
         "rubric_version": rv},
        verdict="green", counts=bucket_counts,
    )
    return 0


# ─── argparse entry ──────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kaizen-brainstorm",
        description="Typed contract for brainstorming JSONL output.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("score", help="Score a brainstorm JSONL through the rubric.")
    sc.add_argument("--input", required=True, help="Path to input JSONL.")
    sc.add_argument("--rubric", required=True, help="Path to brainstorm-rubric.yaml.")
    sc.add_argument("--rewrite", action="store_true",
        help="Atomic in-place rewrite. Default emits envelope to stdout.")
    sc.add_argument("--force", action="store_true",
        help="Required with --rewrite when rubric_version drift detected.")
    sc.add_argument("--max-ideas", type=int, default=None,
        help=f"Hard-stop above N ideas. Default {_DEFAULT_MAX_IDEAS}; "
             f"env KAIZEN_BRAINSTORM_MAX_IDEAS overrides.")
    sc.add_argument("--json", action="store_true",
        help="No-op flag — output is always canonical envelope JSON.")
    sc.set_defaults(func=_cmd_score)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
