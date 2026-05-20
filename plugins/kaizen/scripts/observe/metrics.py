"""kaizen metrics — rollup + never-used + skip-detection CLI.

Public CLI surface over the trace log. Core primitives live in
``_metrics.py`` so the feature matches the canonical feature shape
(``_<feature>.py`` core + ``<feature>.py`` public CLI). This module
is argparse + the ``_cmd_*`` handlers; all the actual logic is
imported from ``_metrics``.

## Subcommands

::

   kaizen-metrics session [--sid SID] [--json]
       Rollup for one session (default: most recent active sid)
   kaizen-metrics lifetime [--since DUR] [--json]
       Rollup over all of trace.jsonl (or --since '7d' / '30d' / ISO)
   kaizen-metrics never-used [--kind skill|tool|mcp|bin] [--json]
       What's available but never invoked
   kaizen-metrics top [--kind skill|tool|mcp] [--n 10] [--json]
       Most-used artifacts of each kind
   kaizen-metrics skips [--sid SID] [--json]
       Skill-skips: files touched without the matching skill loaded
   kaizen-metrics path
       Print the trace log path

Bare invocation (no subcommand) defaults to ``lifetime --since 7d``.
Exit 0 always (informational). Non-zero only on argument errors.

## Why this exists

Until v1.34's M1 universal-trace hook, only Bash tool calls left a
trace footprint. With M1 in place, every Skill / Edit / Write / MCP
invocation lands in the same jsonl. This module is the rollup
surface — without it, the trace is a flat append-only log that's
hard to interrogate. The never-used catalog answers "which feature
have I NEVER used"; skip-detection answers "did I forget to load a
mandatory skill".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent / "io"))

# Core primitives — see _metrics.py. Its `__all__` gates exactly the
# public surface; the star-import re-exports that surface onto the
# `metrics.` namespace so metrics_mcp.py (`import metrics`) and the
# CLI handlers below both reach it. A hand-maintained explicit list
# was tried + dropped — it rotted into dead re-exports (boy-scout +
# YAGNI: __all__ is the single source of truth, no list to maintain).
from _metrics import *  # noqa: F401,F403

# Canonical tool-output envelope — every --json path emits through this
# (programmable + reproducible + consistent JSON across kaizen tools).
# `emitter()` returns a tool-bound closure; per-subcommand calls become
# one-liners.
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-metrics", tool_version="1.0.0")

# ─── CLI ─────────────────────────────────────────────────────────────

def _cmd_session(args) -> int:
    sid = args.sid or latest_session_id()
    if not sid:
        _emit({"sid": None}, verdict=None, counts=None)
        return 0
    r = rollup_events(sid=sid)
    d = r.to_dict()
    d["sid"] = sid
    if args.json:
        _emit(d)
        return 0
    _print_rollup(d, title=f"Session {sid[:12]}")
    return 0

def _cmd_lifetime(args) -> int:
    since = parse_duration(args.since) if args.since else None
    r = rollup_events(since=since)
    d = r.to_dict()
    if args.json:
        _emit(d)
        return 0
    _print_rollup(d, title=f"Lifetime{(' since ' + args.since) if args.since else ''}")
    return 0

def _cmd_never_used(args) -> int:
    result = never_used(args.kind)
    if args.json:
        _emit(result, counts={
            "available": result.get("available_count", result.get("expected_count", 0)),
            "used": result["used_count"],
            "never_used": len(result["never_used"]),
        })
        return 0
    print(f"\n[kaizen-metrics never-used] kind={result['kind']}")
    print(f"  available: {result.get('available_count', result.get('expected_count', 0))}")
    print(f"  used:      {result['used_count']}")
    print(f"  never used: {len(result['never_used'])}")
    if result["never_used"]:
        print()
        for name in result["never_used"]:
            print(f"    - {name}")
    return 0

def _cmd_top(args) -> int:
    items = top_n(args.kind, args.n)
    if args.json:
        _emit([{"name": n, "count": c} for n, c in items],
              counts={"items": len(items)})
        return 0
    print(f"\n[kaizen-metrics top-{args.n}] kind={args.kind}")
    if not items:
        print("  (no data)")
        return 0
    for name, count in items:
        print(f"  {count:>6}  {name}")
    return 0

def _cmd_path(args) -> int:
    _emit({"trace_log": str(trace_log_path())})
    return 0

def _cmd_skips(args) -> int:
    skips = detect_skips(sid=args.sid)
    if args.json:
        _emit({"sid": args.sid or latest_session_id(), "skips": skips},
              counts={"skips": len(skips)})
        return 0
    sid = args.sid or latest_session_id()
    print(f"\n[kaizen-metrics skips] session={sid}")
    if not skips:
        print("  ✓ no skill-skips detected — all triggered skills were loaded")
        return 0
    for s in skips:
        print(f"  ∘ {s['skill']:<24} ({s['touched_count']} file(s) touched)")
        print(f"      reason: {s['rationale']}")
        for p in s["touched_files"][:5]:
            print(f"        {p}")
    return 0

def _cmd_graveyard(args) -> int:
    result = graveyard(kind=args.kind, stale_days=args.stale_days)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"\n[kaizen-metrics graveyard] kind={result['kind']} "
          f"stale_days={result['stale_days']}")
    if not result["ready"]:
        print(f"  ∘ not ready: {result['caveat']}")
        return 0
    cands = result["candidates"]
    print(f"  trace age: {result['trace_age_days']}d  (>= threshold — judging is valid)")
    print(f"  cold candidates: {len(cands)}")
    if cands:
        print()
        for name in cands:
            print(f"    - {name}")
        print()
        print(f"  archive hint: {result['archive_hint']}")
        print(f"  caveat: {result['caveat']}")
    return 0

_NOISE_AXES: list[tuple[str, str]] = [
    # (axis-id, scripts/quality/<file>.py basename)
    ("hook_cascade",  "hook_cascade.py"),
    ("silent_fail",   "silent_fail.py"),
    ("turn_density",  "turn_density.py"),
]

def _run_axis(script: str) -> dict:
    """Invoke one quality axis with `gaps --json`. Returns the parsed
    envelope dict (or {error, rc, stderr} on failure)."""
    import subprocess
    quality_dir = _SCRIPT_DIR.parent / "quality"
    r = subprocess.run(
        ["python3", str(quality_dir / script), "gaps", "--json"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout or "").strip(), "rc": r.returncode,
                "verdict": "red", "counts": {}, "data": {}}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"non-JSON output: {e}", "verdict": "red",
                "counts": {}, "data": {}}

def _rollup_verdict(verdicts: list[str]) -> str:
    """Merge axis verdicts: any red → red; any yellow → yellow; else green."""
    if "red" in verdicts:
        return "red"
    if "yellow" in verdicts:
        return "yellow"
    return "green"

def _cmd_noise(args) -> int:
    """Hook/tool noise dashboard — aggregates the 3 dynamic-trace axes
    (cascade / silent-fail / per-turn density) into one verdict.

    Static wiring axes (hook-coverage / mcp-coverage / *-trace-coverage)
    are NOT included — those are coverage, not noise. Use the
    individual `kaizen-<axis>` bins for those.
    """
    results: dict[str, dict] = {}
    verdicts: list[str] = []
    counts: dict[str, int] = {}
    for axis_id, script in _NOISE_AXES:
        env = _run_axis(script)
        results[axis_id] = env
        verdicts.append(env.get("verdict", "green"))
        # Hoist axis counts up into the consolidated counts dict.
        for k, v in env.get("counts", {}).items():
            counts[f"{axis_id}.{k}"] = v
    verdict = _rollup_verdict(verdicts)

    if args.json:
        _emit({"axes": results}, verdict=verdict, counts=counts)
        return 0

    # Human-readable rollup
    print(f"\n[kaizen-metrics noise] verdict={verdict}")
    for axis_id, env in results.items():
        v = env.get("verdict", "?")
        c = env.get("counts", {})
        c_str = ", ".join(f"{k}={vv}" for k, vv in c.items()) or "(empty)"
        marker = {"green": "✓", "yellow": "∘", "red": "✗"}.get(v, "?")
        print(f"  {marker} {axis_id:<14} {v:<7} {c_str}")
        # Surface the most useful axis-specific detail if present
        data = env.get("data", {})
        if axis_id == "hook_cascade" and data.get("cascades"):
            print(f"      cascades: {len(data['cascades'])}")
        elif axis_id == "silent_fail" and data.get("findings"):
            print(f"      silent-fail hooks: {len(data['findings'])}")
        elif axis_id == "turn_density" and data.get("turns"):
            print(f"      turns scanned: {len(data['turns'])}")
    return 0 if verdict != "red" else 2

def _cmd_smoke(args) -> int:
    if args.kind != "mcp":
        print(json.dumps({"error": f"smoke --kind {args.kind} not implemented "
                                   "(only 'mcp' for now)"}))
        return 1
    result = smoke_mcp()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print("\n[kaizen-metrics smoke] kind=mcp")
    if result.get("skipped"):
        print(f"  ∘ skipped: {result['skipped']}")
        return 0
    print(f"  checked: {result['checked']}  passed: {result['passed']}  "
          f"failed: {len(result['failed'])}")
    if result["failed"]:
        print()
        for f in result["failed"]:
            print(f"    ✗ {f['name']}: {f['error']}")
        return 2
    print("  ✓ all MCP servers import + expose a FastMCP instance")
    return 0

def _print_rollup(d: dict, title: str) -> None:
    print(f"\n[kaizen-metrics] {title}")
    print(f"  events     : {d['total_events']:>6}")
    print(f"  sessions   : {d['sessions']:>6}")
    print(f"  errors     : {d['errors']:>6}")
    print(f"  earliest   : {d.get('earliest_ts', '-')}")
    print(f"  latest     : {d.get('latest_ts', '-')}")
    if d.get("by_tool"):
        print("\n  by_tool (top 10):")
        for name, count in list(d["by_tool"].items())[:10]:
            print(f"    {count:>6}  {name}")
    if d.get("by_skill"):
        print("\n  by_skill (top 10):")
        for name, count in list(d["by_skill"].items())[:10]:
            print(f"    {count:>6}  {name}")
    if d.get("by_mcp"):
        print("\n  by_mcp (top 10):")
        for name, count in list(d["by_mcp"].items())[:10]:
            print(f"    {count:>6}  {name}")

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-metrics",
        description="Rollup + never-used catalog over the kaizen trace log.",
    )
    # required=False so a bare invocation defaults to `lifetime --since 7d`.
    # The `${ARGUMENTS:-default with spaces}` slash-command pattern fails to
    # bash-evaluate when the default has whitespace, so the slash command
    # passes bare `$ARGUMENTS` and relies on this no-arg fallback.
    sub = p.add_subparsers(dest="cmd", required=False)

    s_sess = sub.add_parser("session", help="rollup for one session")
    s_sess.add_argument("--sid", help="session id (default: latest)")
    s_sess.add_argument("--json", action="store_true")
    s_sess.set_defaults(func=_cmd_session)

    s_life = sub.add_parser("lifetime", help="rollup over all events")
    s_life.add_argument("--since", help="duration (7d, 30m, 2w) or ISO timestamp")
    s_life.add_argument("--json", action="store_true")
    s_life.set_defaults(func=_cmd_lifetime)

    s_never = sub.add_parser("never-used", help="features available but never invoked")
    s_never.add_argument("--kind", choices=["skill", "tool", "mcp", "bin"],
                         default="skill")
    s_never.add_argument("--json", action="store_true")
    s_never.set_defaults(func=_cmd_never_used)

    s_top = sub.add_parser("top", help="most-used artifacts of a kind")
    s_top.add_argument("--kind", choices=["skill", "tool", "mcp", "evt"],
                       default="skill")
    s_top.add_argument("--n", type=int, default=10)
    s_top.add_argument("--json", action="store_true")
    s_top.set_defaults(func=_cmd_top)

    s_path = sub.add_parser("path", help="print trace log path")
    s_path.set_defaults(func=_cmd_path)

    s_skips = sub.add_parser(
        "skips",
        help="detect skill-skips: touched files without loading the matching skill",
    )
    s_skips.add_argument("--sid", help="session id (default: latest)")
    s_skips.add_argument("--json", action="store_true")
    s_skips.set_defaults(func=_cmd_skips)

    s_grave = sub.add_parser(
        "graveyard",
        help="cold-artifact candidates: never-used over a trace old enough to judge",
    )
    s_grave.add_argument("--kind", choices=["skill", "mcp", "bin", "tool"],
                         default="skill")
    s_grave.add_argument("--stale-days", type=int, default=14,
                         help="min trace-watch age before flagging (default 14)")
    s_grave.add_argument("--json", action="store_true")
    s_grave.set_defaults(func=_cmd_graveyard)

    s_noise = sub.add_parser(
        "noise",
        help="hook/tool noise dashboard — cascade + silent-fail + turn-density rollup",
    )
    s_noise.add_argument("--json", action="store_true")
    s_noise.set_defaults(func=_cmd_noise)

    s_smoke = sub.add_parser(
        "smoke",
        help="smoke-test: import each MCP server, verify FastMCP instance + tools",
    )
    s_smoke.add_argument("--kind", choices=["mcp"], default="mcp")
    s_smoke.add_argument("--json", action="store_true")
    s_smoke.set_defaults(func=_cmd_smoke)

    args = p.parse_args(argv)
    if args.cmd is None:
        # Bare invocation — default to the 7-day lifetime rollup.
        return _cmd_lifetime(argparse.Namespace(since="7d", json=False))
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
