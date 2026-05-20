#!/usr/bin/env python3
"""kaizen-chatlog — trigger-rule-driven CC transcript slicer (MVP).

Reads a Claude Code transcript JSONL (typically at
``~/.claude/projects/<slug>/<sid>.jsonl``), matches each event against a
list of trigger rules, captures a window around each match, and writes
one ``.jsonl`` per rule into the out dir.

## Usage

    kaizen-chatlog slice \\
        --transcript ~/.claude/projects/<slug>/<sid>.jsonl \\
        --rules path/to/rules.{yaml,json} \\
        --out ~/.claude/.kaizen/chatlog/<sid>/

    # JSON output for scripting
    kaizen-chatlog slice ... --json

## Rules file (JSON or YAML)

    rules:
      - id: gate_failures
        trigger:
          type: user_keyword
          pattern: "gate.*fail"
        capture:
          before: 1
          after: 5
      - id: handoff_calls
        trigger:
          type: assistant_tool_use
          tool_name: handoff
        capture:
          before: 0
          after: 1

Trigger types (v1): event_type / user_keyword / assistant_tool_use.

Output: one JSONL per rule at ``<out>/<rule_id>.jsonl`` — each line is
ONE slice (JSON array of events).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _chatlog  # noqa: E402

def _load_rules(rules_path: Path) -> list[dict]:
    """Load rules from JSON or YAML. Returns the rules list."""
    text = rules_path.read_text(encoding="utf-8")
    data: dict
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise SystemExit(
                f"chatlog: rules file isn't valid JSON and PyYAML unavailable: {e}"
            )
        data = yaml.safe_load(text) or {}
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise SystemExit("chatlog: rules file must contain a top-level `rules:` list")
    return rules

def _load_transcript(transcript_path: Path) -> list[dict]:
    """Load a JSONL transcript; skip malformed lines silently."""
    if not transcript_path.is_file():
        raise SystemExit(f"chatlog: transcript not found: {transcript_path}")
    events = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events

def cmd_slice(args) -> int:
    transcript = Path(args.transcript).expanduser()
    rules_path = Path(args.rules).expanduser()
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    events = _load_transcript(transcript)
    rules = _load_rules(rules_path)
    sliced = _chatlog.slice_transcript(events, rules)

    counts: dict[str, int] = {}
    for rule_id, slices in sliced.items():
        path = out_dir / f"{rule_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for sl in slices:
                f.write(json.dumps(sl, separators=(",", ":")) + "\n")
        counts[rule_id] = len(slices)

    if args.json:
        print(json.dumps({
            "counts": counts,
            "out_dir": str(out_dir),
            "rules_file": str(rules_path),
            "transcript": str(transcript),
            "total_events": len(events),
        }, indent=2))
    else:
        print(f"chatlog: sliced {len(events)} events against {len(rules)} rule(s)")
        for rid, n in counts.items():
            print(f"  {rid:<24} {n} match(es)")
        print(f"  → {out_dir}")
    return 0

def main() -> None:
    p = argparse.ArgumentParser(
        prog="kaizen-chatlog", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sl = sub.add_parser("slice", help="extract trigger-matched slices from a transcript")
    sl.add_argument("--transcript", required=True,
                     help="path to CC transcript .jsonl")
    sl.add_argument("--rules", required=True,
                     help="path to rules .json/.yaml")
    sl.add_argument("--out", required=True,
                     help="output directory (one .jsonl per rule)")
    sl.add_argument("--json", action="store_true",
                     help="emit machine-readable summary on stdout")

    args = p.parse_args()
    if args.cmd == "slice":
        sys.exit(cmd_slice(args))
    p.print_help()
    sys.exit(2)

if __name__ == "__main__":
    main()
