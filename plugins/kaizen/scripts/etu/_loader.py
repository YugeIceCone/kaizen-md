#!/usr/bin/env python3
"""kaizen efficient-tool-use — yaml domain loader.

Loads + validates skills/efficient-tool-use/domain/anti-patterns.yaml
against skills/efficient-tool-use/domain/schemas/anti-pattern.schema.json.
Mirrors skills/karpathy/application/_loader.py + skills/workflow/application/_loader.py.

## CLI

    python3 _loader.py validate           # validate anti-patterns.yaml; exit non-zero on error
    python3 _loader.py list               # list anti-pattern ids (one per line)
    python3 _loader.py show <id>          # print one anti-pattern as JSON
    python3 _loader.py by-tool <tool>     # filter by tool (grep|sed|find|bash|xargs|jq|awk|shell-general)
    python3 _loader.py detect             # list ids that have a `detect` regex (scanner-ready)

## Stdlib + minimal deps

Requires PyYAML. The `jsonschema` library is optional — if absent, validation
is skipped with a warning (matches the constrained-CI-sandbox degradation
policy from workflow/_loader.py + karpathy/_loader.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    sys.stderr.write("kaizen efficient-tool-use loader: PyYAML required (pip install pyyaml)\n")
    sys.exit(2)

try:
    from jsonschema import validate as _jsonschema_validate, ValidationError  # type: ignore[import-untyped]
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

DOMAIN_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "efficient-tool-use" / "domain"
)
ANTI_PATTERNS_YAML = DOMAIN_DIR / "anti-patterns.yaml"
ANTI_PATTERN_SCHEMA = DOMAIN_DIR / "schemas" / "anti-pattern.schema.json"


def _die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"kaizen efficient-tool-use loader: {msg}\n")
    sys.exit(code)


def load_anti_patterns() -> dict:
    """Load anti-patterns.yaml. Validates against anti-pattern.schema.json when jsonschema is available."""
    if not ANTI_PATTERNS_YAML.exists():
        _die(f"anti-patterns.yaml not found at {ANTI_PATTERNS_YAML}", 3)
    if not ANTI_PATTERN_SCHEMA.exists():
        _die(f"anti-pattern.schema.json not found at {ANTI_PATTERN_SCHEMA}", 3)
    with ANTI_PATTERNS_YAML.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        _die("anti-patterns.yaml must contain a top-level mapping")
    if _HAS_JSONSCHEMA:
        try:
            schema = json.loads(ANTI_PATTERN_SCHEMA.read_text())
            _jsonschema_validate(instance=data, schema=schema)
        except ValidationError as e:
            _die(f"anti-patterns.yaml fails schema:\n  {e.message}\n  path: {list(e.absolute_path)}")
    else:
        sys.stderr.write(
            "kaizen efficient-tool-use loader: jsonschema not installed — validation skipped\n"
        )
    return data


def _anti_pattern(data: dict, ap_id: str) -> dict:
    for ap in data.get("anti_patterns", []):
        if ap.get("id") == ap_id:
            return ap
    _die(f"unknown anti-pattern id: {ap_id}")
    return {}  # unreachable


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    cmd = argv[0]
    data = load_anti_patterns()
    aps = data.get("anti_patterns", [])
    if cmd == "validate":
        print(f"anti-patterns.yaml: valid ({len(aps)} entries)")
        return 0
    if cmd == "list":
        for ap in aps:
            print(ap["id"])
        return 0
    if cmd == "show":
        if len(argv) < 2:
            _die("show <id> requires an id arg")
        print(json.dumps(_anti_pattern(data, argv[1]), indent=2))
        return 0
    if cmd == "by-tool":
        if len(argv) < 2:
            _die("by-tool <tool> requires a tool arg")
        tool = argv[1]
        matches = [ap for ap in aps if ap.get("tool") == tool]
        if not matches:
            _die(f"no anti-patterns for tool: {tool}")
        for ap in matches:
            print(ap["id"])
        return 0
    if cmd == "detect":
        scanner_ready = [ap for ap in aps if ap.get("detect")]
        for ap in scanner_ready:
            print(f"{ap['id']}\t{ap['detect']}")
        return 0
    _die(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
