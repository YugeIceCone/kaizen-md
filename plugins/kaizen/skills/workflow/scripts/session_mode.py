"""kaizen session_mode — record + read the session intake choice.

At SessionStart the intake hook asks "loop, workflow, or neither?"
The user's answer routes future agent behavior:

  loop      → agent runs /kaizen:loop with its prompt
  workflow  → agent runs /workflow with a routine
  neither   → no kaizen-loop / no workflow scaffolding

This module is the persistence layer — small enough to live in one
file (KISS). Storage is a JSON file at `.kaizen/session-mode.json`
(override with KAIZEN_SESSION_MODE_PATH for tests).

CLI:

    session_mode.py set <mode> [--skills DRY,KISS,...] [--session-id ID]
    session_mode.py get [--json]
    session_mode.py clear
    session_mode.py exists                  # exit 0 iff a mode is set

Modes: loop | workflow | neither.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path


_VALID_MODES = ("loop", "workflow", "neither")


# Discipline bundles — picked by the SessionStart QA multiSelect.
# Logical grouping so users don't have to pick 13 individual skills.
# Each bundle expands to a flat list of skill tags that downstream
# hooks/agents use to filter behaviour.
#
#   simplicity → anti-bloat (small code, no premature abstraction)
#   structure  → architecture (boundaries, layering, dependency direction)
#   process    → how-you-work (test-first, leave-it-cleaner, convention-over-config)
#   karpathy   → code-as-communication (Karpathy's 4 principles)
_BUNDLES: dict[str, list[str]] = {
    "simplicity": ["kiss", "yagni", "dry"],
    # Structure = all the layered / inward-deps / boundary disciplines.
    # SOLID + SoC + LoD are the OO classics. Onion / Clean / Hexagonal /
    # Ports-and-Adapters / DIP / Bounded-Contexts are the layered-system
    # vein — consolidated upstream by skills/onion-ddd-workflow (which
    # itself lists Onion / Clean / Hexagonal / Ports & Adapters / DIP /
    # Palermo / DDD as the family). Same vein, picked together.
    "structure":  [
        "solid", "soc", "lod",
        "onion-ddd", "hexagonal", "clean-arch", "dip", "bounded-contexts",
    ],
    "process":    ["tdd", "boy-scout", "convention"],
    "karpathy":   ["karpathy"],
}


# Per-skill short descriptions for the per-prompt reminder hook.
# One imperative line each — the agent re-reads these every turn so
# they have to sting. NOT the same as the SKILL.md description (which
# is for skill-load routing); these are stay-on-target reminders for
# already-active disciplines.
_SKILL_DESCRIPTIONS: dict[str, str] = {
    # Simplicity
    "kiss":             "keep it simple — fewest moving parts wins",
    "yagni":            "no speculative abstraction — only what THIS task needs",
    "dry":              "no duplication — extract on 2nd repetition, not 1st",
    # Structure
    "solid":            "SOLID — single responsibility, open-closed, DIP",
    "soc":              "separation of concerns — logic / I/O / presentation split",
    "lod":              "law of demeter — talk to friends, not strangers",
    "onion-ddd":        "onion + DDD — inward-only deps, ports at boundaries",
    "hexagonal":        "hexagonal — adapters at the edges, core domain pure",
    "clean-arch":       "clean architecture — entities → use-cases → adapters",
    "dip":              "dependency inversion — high-level depends on abstractions",
    "bounded-contexts": "bounded contexts — explicit context boundaries + lints",
    # Process
    "tdd":              "TDD — RED first, GREEN clean, refactor third",
    "boy-scout":        "boy-scout — leave touched code cleaner than found",
    "convention":       "convention over config — match existing patterns FIRST",
    # Karpathy
    "karpathy":         "Karpathy 4 — write code that reads like its intent",
}


def describe_skill(skill_id: str) -> str:
    """One-liner for a skill id, or the bare id when unknown."""
    return _SKILL_DESCRIPTIONS.get(skill_id, skill_id)


def expand_bundles(bundle_csv: str) -> list[str]:
    """Expand a comma-separated list of bundle names to a flat list of
    skill tags. Unknown bundles are silently dropped (we don't want
    the agent's typo to abort the whole intake). Order preserved per
    bundle; duplicates de-duped at merge time."""
    out: list[str] = []
    for raw in bundle_csv.split(","):
        name = raw.strip().lower()
        if not name or name not in _BUNDLES:
            continue
        out.extend(_BUNDLES[name])
    return out


def _merge_unique(*lists: list[str]) -> list[str]:
    """Concatenate lists preserving first-seen order, deduping case-sensitive."""
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for x in lst:
            if x not in seen:
                seen.add(x)
                out.append(x)
    return out


def _state_path() -> Path:
    env = os.environ.get("KAIZEN_SESSION_MODE_PATH")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path(".kaizen") / "session-mode.json"


def _iso_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state() -> dict | None:
    path = _state_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(data: dict) -> bool:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def _cmd_set(args) -> int:
    if args.mode not in _VALID_MODES:
        sys.stderr.write(
            f"[kaizen-session-mode set] invalid mode {args.mode!r}; "
            f"choose from {', '.join(_VALID_MODES)}\n"
        )
        return 2
    # Skills resolution: --bundles expands first, then --skills CSV
    # adds individual tags on top. De-duped, order preserved.
    from_bundles = expand_bundles(args.bundles or "")
    from_skills = [s.strip().lower() for s in (args.skills or "").split(",") if s.strip()]
    state = {
        "mode":       args.mode,
        "set_at":     _iso_now(),
        "session_id": args.session_id or "",
        "skills":     _merge_unique(from_bundles, from_skills),
        "bundles":    [b.strip().lower() for b in (args.bundles or "").split(",") if b.strip()],
    }
    if not write_state(state):
        sys.stderr.write("[kaizen-session-mode set] write failed\n")
        return 1
    print(json.dumps(state))
    return 0


def _cmd_get(args) -> int:
    state = read_state()
    if state is None:
        if args.json:
            print(json.dumps({"mode": None}))
        return 1
    if args.json:
        print(json.dumps(state))
    else:
        print(state.get("mode", ""))
    return 0


def _cmd_clear(args) -> int:
    path = _state_path()
    try:
        path.unlink(missing_ok=True)
        return 0
    except OSError:
        return 1


def _cmd_exists(args) -> int:
    return 0 if read_state() is not None else 1


def _cmd_bundles(args) -> int:
    """Print the bundle catalog so callers (intake hook, agents,
    downstream consumers) can introspect without re-importing."""
    if args.json:
        print(json.dumps(_BUNDLES, indent=2))
    else:
        for name, skills in _BUNDLES.items():
            print(f"{name}: {', '.join(skills)}")
    return 0


def _cmd_reminder(args) -> int:
    """Emit the active-skills reminder for hook injection.

    Reads .kaizen/session-mode.json's skills[] and prints one block:

        kaizen disciplines pinned: <comma list>
          - <skill1>: <description>
          - <skill2>: <description>

    Empty output (exit 0) when no state, no skills, or all skills
    unknown — the hook treats that as no-op.
    """
    state = read_state()
    if state is None:
        return 0
    skills = state.get("skills") or []
    if not skills:
        return 0
    known = [s for s in skills if s in _SKILL_DESCRIPTIONS]
    if not known:
        return 0
    if args.json:
        print(json.dumps({
            "skills": [{"id": s, "description": _SKILL_DESCRIPTIONS[s]}
                        for s in known],
        }))
        return 0
    # Compact text form (default — what the hook injects)
    print(f"kaizen disciplines pinned: {', '.join(known)}")
    for s in known:
        print(f"  - {s}: {_SKILL_DESCRIPTIONS[s]}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kaizen-session-mode",
                                  description="Record / read session intake mode.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("set", help="record the mode for this session")
    ps.add_argument("mode", choices=_VALID_MODES)
    ps.add_argument("--skills", default="",
                     help="comma-separated discipline tags (dry,kiss,tdd,solid,...)")
    ps.add_argument("--bundles", default="",
                     help="comma-separated bundle names (simplicity,structure,process,karpathy)")
    ps.add_argument("--session-id", default="",
                     help="optional Claude Code session-id pin")
    ps.set_defaults(func=_cmd_set)

    pg = sub.add_parser("get", help="print the active mode")
    pg.add_argument("--json", action="store_true",
                     help="emit full state record as JSON")
    pg.set_defaults(func=_cmd_get)

    pc = sub.add_parser("clear", help="remove the state file")
    pc.set_defaults(func=_cmd_clear)

    pe = sub.add_parser("exists", help="exit 0 iff a mode is set; for hook gating")
    pe.set_defaults(func=_cmd_exists)

    pb = sub.add_parser("bundles", help="print the discipline-bundle catalog")
    pb.add_argument("--json", action="store_true")
    pb.set_defaults(func=_cmd_bundles)

    pr = sub.add_parser("reminder",
                          help="emit the active-skills reminder block (for hook injection)")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=_cmd_reminder)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
