"""kaizen-rubric — standalone CLI for prototyping data-driven rubrics.

Exposes ``schema_cli.BucketWalker`` as a bare CLI so an agent can
iterate on a rubric YAML before wiring it into a feature CLI. Used
by the ``decision-rubric`` skill (SKILL.md) as the recommended dev
loop:

  1. Sketch a rubric in YAML.
  2. ``kaizen-rubric lint --rubric R.yaml`` to catch unknown ops / shape.
  3. ``kaizen-rubric eval --rubric R.yaml --signals '{"x":1}'`` to test
     classification before writing the consumer feature.

Output goes through ``_envelope.emitter`` so the result is
canonical-envelope shaped — same lens contract as every other
kaizen tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402
import schema_cli  # noqa: E402

_emit = _envelope.emitter("kaizen-rubric", tool_version="1.0.0")


def _cmd_eval(args) -> int:
    rp = Path(args.rubric).expanduser()
    if not rp.is_file():
        print(f"[kaizen-rubric eval] rubric not found: {rp}", file=sys.stderr)
        return 1

    # Source signals
    if args.signals_file:
        sig_text = Path(args.signals_file).expanduser().read_text(encoding="utf-8")
    elif args.signals is not None:
        sig_text = args.signals
    else:
        sig_text = sys.stdin.read() if not sys.stdin.isatty() else "{}"

    try:
        signals = json.loads(sig_text or "{}")
    except json.JSONDecodeError as exc:
        print(f"[kaizen-rubric eval] signals not valid JSON: {exc}",
              file=sys.stderr)
        return 2

    try:
        walker = schema_cli.BucketWalker.from_yaml(rp)
    except schema_cli.RuleError as exc:
        print(f"[kaizen-rubric eval] rubric malformed: {exc}", file=sys.stderr)
        return 2

    result = walker.evaluate(signals)
    data = {
        "bucket":     result.bucket,
        "method":     result.method,
        "confidence": float(result.confidence),
        "rationale":  result.rationale,
        "rubric":     str(rp.resolve()),
        "signals":    signals,
    }
    if args.json:
        verdict = "green" if result.method == "deterministic" else "yellow"
        _emit(data, verdict=verdict)
    else:
        print(f"[kaizen-rubric eval] {rp.resolve()}")
        print(f"  bucket:    {result.bucket}")
        print(f"  method:    {result.method}  (confidence {result.confidence:.2f})")
        print(f"  rationale: {result.rationale}")
        print(f"  signals:   {signals}")
    return 0


def _cmd_lint(args) -> int:
    rp = Path(args.rubric).expanduser()
    if not rp.is_file():
        print(f"[kaizen-rubric lint] rubric not found: {rp}", file=sys.stderr)
        return 1
    try:
        walker = schema_cli.BucketWalker.from_yaml(rp)
    except schema_cli.RuleError as exc:
        msg = f"rubric rejected: {exc}"
        if args.json:
            _emit({"verdict": "broken", "rubric": str(rp.resolve()),
                    "error": str(exc)}, verdict="red")
        else:
            print(f"[kaizen-rubric lint] {msg}", file=sys.stderr)
        return 2

    data = {
        "verdict":          "clean",
        "rubric":           str(rp.resolve()),
        "rule_count":       len(walker.rules),
        "fallback":         walker.fallback,
        "confidence_threshold": walker.confidence_threshold,
    }
    if args.json:
        _emit(data, verdict="green")
    else:
        print(f"[kaizen-rubric lint] {rp.resolve()}")
        print(f"  verdict:  clean")
        print(f"  rules:    {len(walker.rules)}")
        print(f"  fallback: {walker.fallback}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-rubric",
        description="Prototype + lint data-driven rubrics (BucketWalker shape) "
                    "before wiring into a feature CLI.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    se = sub.add_parser("eval",
                         help="walk a rubric against a signals dict")
    se.add_argument("--rubric", required=True, help="path to rubric YAML")
    src = se.add_mutually_exclusive_group()
    src.add_argument("--signals", default=None,
                      help="JSON string of signals dict")
    src.add_argument("--signals-file", default=None,
                      help="path to JSON file of signals dict")
    se.add_argument("--json", action="store_true")
    se.set_defaults(func=_cmd_eval)

    sl = sub.add_parser("lint", help="validate rubric structural shape")
    sl.add_argument("--rubric", required=True, help="path to rubric YAML")
    sl.add_argument("--json", action="store_true")
    sl.set_defaults(func=_cmd_lint)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
