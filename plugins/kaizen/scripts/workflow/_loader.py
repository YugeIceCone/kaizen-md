#!/usr/bin/env python3
"""Kaizen workflow — yaml domain loader.

Loads + validates schemas/workflow/{routines.yaml, git-discipline.yaml}
against their JSON Schemas. Exposes a small CLI for shell consumers (workflow.sh,
pre-commit.sh) and a Python API for codegen.py + tests.

## CLI

    python3 _loader.py validate           # validate both yamls; exit non-zero on error
    python3 _loader.py list               # list routine names (one per line)
    python3 _loader.py stages <name>      # print stage chain (space-separated, one line)
    python3 _loader.py routine <name>     # print full routine entry as JSON
    python3 _loader.py triggers           # print "name\\tword1,word2" for each routine
    python3 _loader.py gates              # print gate ids (one per line)
    python3 _loader.py gate <id>          # print gate definition as JSON

## Stdlib + minimal deps

Requires pyyaml. The jsonschema lib is optional — if absent, validation is
skipped with a warning (no fatal error). This keeps the loader runnable in
constrained environments (e.g. snap-confined ruff/ty contexts).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# H1 dedup: shared YAML + JSON-Schema helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _yaml import load_yaml as _load_yaml  # noqa: E402
from _yaml import validate as _check  # noqa: E402

DOMAIN_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "schemas" / "workflow"
)
ROUTINES_YAML = DOMAIN_DIR / "routines.yaml"
GIT_DISCIPLINE_YAML = DOMAIN_DIR / "git-discipline.yaml"
ROUTINE_SCHEMA = DOMAIN_DIR / "schemas" / "routine.schema.json"
GIT_RULES_SCHEMA = DOMAIN_DIR / "schemas" / "git-rules.schema.json"

def load_routines() -> dict[str, dict]:
    """Return routines indexed by name. Validates against routine.schema.json."""
    data = _load_yaml(ROUTINES_YAML)
    _check(data, ROUTINE_SCHEMA, "routines.yaml")
    return {r["name"]: r for r in data.get("routines", [])}

def load_stage_skill_map() -> dict[str, str]:
    """Return the `stage_skill_map` block as a flat {stage: skill} dict.

    Phase C — wires every workflow stage to its implementing kaizen skill.
    Stages without a mapping resolve to None (caller decides fallback)."""
    data = _load_yaml(ROUTINES_YAML)
    _check(data, ROUTINE_SCHEMA, "routines.yaml")
    return dict(data.get("stage_skill_map") or {})

def get_skill_for_stage(stage: str) -> str | None:
    """Look up the kaizen skill that implements a stage. Returns None
    when the stage isn't in the map (e.g. `simplify`, schema internals)."""
    return load_stage_skill_map().get(stage)

def load_defaults() -> dict:
    """Return the `defaults` block (routing backstops). Validates lazily.

    Shape: `{"routine": "<name>", "stages": ["<stage>", ...]}`. Pre-Phase-B
    yamls without the block fall back to safe baked-in values so the bash
    wrappers don't break mid-migration."""
    data = _load_yaml(ROUTINES_YAML)
    _check(data, ROUTINE_SCHEMA, "routines.yaml")
    d = data.get("defaults") or {}
    return {
        "routine": d.get("routine", "build-feature"),
        "stages": d.get("stages", ["explore", "analyze", "create-plan", "create-tasks"]),
    }

def load_git_discipline() -> dict:
    """Return git-discipline yaml as a plain dict. Validates against git-rules.schema.json."""
    data = _load_yaml(GIT_DISCIPLINE_YAML)
    _check(data, GIT_RULES_SCHEMA, "git-discipline.yaml")
    return data

def get_routine(name: str) -> dict | None:
    return load_routines().get(name)

def get_stages(name: str) -> list[str]:
    """Return the stage chain for a routine.

    Resolution:
    - Unknown routine name → `defaults.stages` from the yaml (Phase B backstop).
    - Known routine → its declared stages, EVEN IF EMPTY (e.g. `custom` is
      the documented opt-out for user-pinned-skill workflows).
    """
    r = get_routine(name)
    if r is None:
        return load_defaults()["stages"]
    return r.get("stages") or []

def detect_routine(prompt: str) -> str:
    """Mirror workflow.sh::detect_routine — pick a routine by verb match.

    Iterates routines in yaml order, returning the first routine whose
    trigger_words substring-match the lowercased prompt. Falls back to
    `defaults.routine` from the yaml.
    """
    p = (prompt or "").lower()
    for name, r in load_routines().items():
        if r.get("kind") != "hardcoded":
            continue
        for word in r.get("trigger_words") or []:
            if word.lower() in p:
                return name
    return load_defaults()["routine"]

def verb_matched_explicitly(prompt: str) -> bool:
    """True iff some hardcoded routine's trigger_words substring-match the prompt."""
    p = (prompt or "").lower()
    for r in load_routines().values():
        if r.get("kind") != "hardcoded":
            continue
        for word in r.get("trigger_words") or []:
            if word.lower() in p:
                return True
    return False

# ─── CLI ─────────────────────────────────────────────────────────────────

def _cli() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0

    cmd = argv[0]
    args = argv[1:]

    if cmd == "validate":
        load_routines()
        load_git_discipline()
        load_defaults()
        print("ok")
        return 0

    if cmd == "defaults":
        json.dump(load_defaults(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "stage-skill":
        if not args:
            sys.stderr.write("usage: _loader.py stage-skill <stage>\n")
            return 2
        skill = get_skill_for_stage(args[0])
        if skill is None:
            sys.stderr.write(f"[loader] stage '{args[0]}' not in stage_skill_map\n")
            return 1
        print(skill)
        return 0

    if cmd == "stage-skill-map":
        json.dump(load_stage_skill_map(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "list":
        for name in load_routines():
            print(name)
        return 0

    if cmd == "stages":
        if not args:
            sys.stderr.write("usage: _loader.py stages <routine-name>\n")
            return 2
        stages = get_stages(args[0])
        if not stages and args[0] != "custom":
            sys.stderr.write(f"[loader] routine '{args[0]}' not found or has empty stages\n")
            return 1
        print(" ".join(stages))
        return 0

    if cmd == "routine":
        if not args:
            sys.stderr.write("usage: _loader.py routine <name>\n")
            return 2
        r = get_routine(args[0])
        if r is None:
            sys.stderr.write(f"[loader] routine '{args[0]}' not found\n")
            return 1
        json.dump(r, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "triggers":
        for name, r in load_routines().items():
            if r.get("kind") != "hardcoded":
                continue
            words = r.get("trigger_words") or []
            print(f"{name}\t{','.join(words)}")
        return 0

    if cmd == "detect":
        if not args:
            sys.stderr.write("usage: _loader.py detect '<prompt>'\n")
            return 2
        print(detect_routine(" ".join(args)))
        return 0

    if cmd == "matched":
        if not args:
            sys.stderr.write("usage: _loader.py matched '<prompt>'\n")
            return 2
        return 0 if verb_matched_explicitly(" ".join(args)) else 1

    if cmd == "gates":
        g = load_git_discipline()
        for gate in g.get("pre_commit_gates", []):
            print(gate["id"])
        return 0

    if cmd == "gate":
        if not args:
            sys.stderr.write("usage: _loader.py gate <id>\n")
            return 2
        g = load_git_discipline()
        for gate in g.get("pre_commit_gates", []):
            if gate["id"] == args[0]:
                json.dump(gate, sys.stdout, indent=2)
                sys.stdout.write("\n")
                return 0
        sys.stderr.write(f"[loader] gate '{args[0]}' not found\n")
        return 1

    sys.stderr.write(f"[loader] unknown command: {cmd}\n")
    return 2

if __name__ == "__main__":
    sys.exit(_cli())
