#!/usr/bin/env python3
"""kaizen-axis-runner — declarative YAML-as-axis loader + dispatcher.

A coverage axis can be declared as a YAML file under
`skills/workflow/domain/axes/<name>.yaml`:

    name: trailing-ws
    scan_spec:
      type: grep
      pattern: " +$"
      glob: "docs/*.md"
    verdict_rule:
      green_max: 0
      yellow_max: 10

`run_axis(yaml_path, root)` loads → validates → dispatches by
`scan_spec.type` → returns the canonical envelope. Subsumes simple
standalone-Python axes (grep / single AST rule / file-coverage)
without writing a new .py file per axis.

CLI verbs:
    kaizen-axis-runner list                  # list axes under domain/axes/
    kaizen-axis-runner run --axis <path>     # run one axis, emit envelope
    kaizen-axis-runner report --axis <path>  # alias for `run`

`jsonschema` is opt-in: when present, the loader validates the YAML
against axis.schema.json; when missing, the loader still parses and
runs (graceful-fallback per `lazy-heavy-deps` iron-law).

Refs: /tmp/axis-runner.blueprint.json items 03-05, 08.3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
# Canonical layout (post-BK-059 migration): scripts/quality/ sits at depth 2
# under plugins/kaizen/, so siblings are at _SCRIPT_DIR.parent (= scripts/).
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-axis-runner", tool_version="1.0.0")
_PLUGIN_ROOT = _SCRIPT_DIR.parents[1]
_SCHEMA_PATH = (
    _PLUGIN_ROOT / "skills/workflow/domain/schemas/axis.schema.json"
)
_AXES_DIR = _PLUGIN_ROOT / "skills/workflow/domain/axes"


# --- YAML loader (graceful-fallback) ---------------------------------------

def _load_yaml(path: Path) -> dict:
    """Parse a YAML file. PyYAML is required (kaizen-wide dep) —
    no flow-style fallback. Axis YAML files are small + author-written;
    PyYAML's parser is the only supported backend."""
    import yaml  # PyYAML — kaizen-wide dep
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _is_jsonschema_available() -> bool:
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False


def _validate_spec(spec: dict) -> None:
    """Validate against axis.schema.json when jsonschema is installed;
    otherwise no-op (graceful-fallback)."""
    if not _is_jsonschema_available():
        return
    import json

    import jsonschema
    with _SCHEMA_PATH.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=spec, schema=schema)


def load(yaml_path: Path | str) -> dict:
    """Load + validate an axis YAML. Returns the parsed dict (AxisSpec
    is just `dict` — keep it stdlib-friendly)."""
    p = Path(yaml_path)
    spec = _load_yaml(p)
    _validate_spec(spec)
    return spec


# --- Dispatch + verdict -----------------------------------------------------

def _verdict_for(n: int, rule: dict) -> str:
    if n <= rule.get("green_max", 0):
        return "green"
    if n <= rule.get("yellow_max", 0):
        return "yellow"
    return "red"


def _dispatch(spec: dict, *, root: Path) -> list[dict]:
    import axis_runner_rules as rules
    scan = spec["scan_spec"]
    t = scan["type"]
    if t == "grep":
        return rules.run_grep(scan["pattern"], scan["glob"], root)
    if t == "ast-rule":
        return rules.run_ast_rule(scan["rule"], scan["glob"], root)
    if t == "file-coverage":
        return rules.run_file_coverage(
            scan["expected_glob"], scan["actual_glob"], root,
        )
    raise ValueError(f"unknown scan_spec.type: {t!r}")


def run_axis(yaml_path: Path | str, *, root: Path | str) -> dict:
    """Load → dispatch → return canonical envelope.

    Args:
      yaml_path: path to the axis YAML
      root:      directory the scan_spec.glob is resolved relative to
    """
    spec = load(yaml_path)
    findings = _dispatch(spec, root=Path(root))
    n = len(findings)
    verdict = _verdict_for(n, spec.get("verdict_rule") or {})
    envelope = _envelope.wrap(
        tool="kaizen-axis-runner",
        tool_version="1.0.0",
        data={"axis": spec.get("name"), "findings": findings,
              "finding_count": n},
        verdict=verdict,
        counts={"findings": n},
    )
    return envelope


# --- CLI --------------------------------------------------------------------

def _cmd_list(_args) -> int:
    if not _AXES_DIR.is_dir():
        _emit({"axes": []}, verdict="green", counts={"axes": 0})
        return 0
    axes = sorted(p.stem for p in _AXES_DIR.glob("*.yaml"))
    _emit({"axes": axes}, verdict="green", counts={"axes": len(axes)})
    return 0


def _cmd_run(args) -> int:
    yaml_path = Path(args.axis)
    if not yaml_path.is_absolute() and not yaml_path.exists():
        # Try resolving as a stem under domain/axes/
        for candidate in (
            _AXES_DIR / yaml_path,
            _AXES_DIR / f"{yaml_path}.yaml",
            _AXES_DIR / f"{yaml_path}.yml",
        ):
            if candidate.exists():
                yaml_path = candidate
                break
    root = Path(args.root) if args.root else _PLUGIN_ROOT
    envelope = run_axis(yaml_path, root=root)
    print(_envelope.render(envelope))
    return 0 if envelope["verdict"] in ("green", "yellow") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kaizen-axis-runner",
        description="Declarative YAML-as-axis loader + dispatcher.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List axes in domain/axes/")
    p_list.set_defaults(func=_cmd_list)

    for verb in ("run", "report"):
        p = sub.add_parser(verb, help=f"{verb} one axis")
        p.add_argument("--axis", required=True,
                       help="axis YAML path (absolute, or stem under domain/axes/)")
        p.add_argument("--root", default=None,
                       help="scan root (default: plugin root)")
        p.add_argument("--json", action="store_true",
                       help="emit JSON envelope (default; flag kept for "
                            "convention parity with sibling scripts/quality/ CLIs)")
        p.set_defaults(func=_cmd_run)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
