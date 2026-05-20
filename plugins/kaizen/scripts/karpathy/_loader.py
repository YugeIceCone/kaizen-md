#!/usr/bin/env python3
"""kaizen karpathy — yaml domain loader.

Loads + validates schemas/karpathy/principles.yaml against
schemas/karpathy/schemas/principle.schema.json. Closes the
orphan-schema gap (schema existed but had no validator).

## CLI

    python3 _loader.py validate           # validate principles.yaml; exit non-zero on error
    python3 _loader.py list               # list principle ids (one per line)
    python3 _loader.py principle <id>     # print one principle entry as JSON
    python3 _loader.py scanners           # list scanner script names referenced by principles

## Stdlib + minimal deps

Requires PyYAML. The `jsonschema` library is optional — if absent, validation
is skipped with a warning (matches workflow/_loader.py's degradation policy
for constrained CI sandboxes).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    sys.stderr.write("kaizen karpathy loader: PyYAML required (pip install pyyaml)\n")
    sys.exit(2)

try:
    from jsonschema import validate as _jsonschema_validate, ValidationError  # type: ignore[import-untyped]
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

# Domain yaml stays with the skill (schemas/karpathy/); only the
# .py adapter migrated to scripts/karpathy/.
DOMAIN_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "schemas" / "karpathy"
)
PRINCIPLES_YAML = DOMAIN_DIR / "principles.yaml"
PRINCIPLE_SCHEMA = DOMAIN_DIR / "schemas" / "principle.schema.json"

def _die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"kaizen karpathy loader: {msg}\n")
    sys.exit(code)

def load_principles() -> dict:
    """Load principles.yaml. Validates against principle.schema.json when jsonschema is available."""
    if not PRINCIPLES_YAML.exists():
        _die(f"principles.yaml not found at {PRINCIPLES_YAML}", 3)
    if not PRINCIPLE_SCHEMA.exists():
        _die(f"principle.schema.json not found at {PRINCIPLE_SCHEMA}", 3)
    with PRINCIPLES_YAML.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        _die("principles.yaml must contain a top-level mapping")
    if _HAS_JSONSCHEMA:
        try:
            schema = json.loads(PRINCIPLE_SCHEMA.read_text())
            _jsonschema_validate(instance=data, schema=schema)
        except ValidationError as e:
            _die(f"principles.yaml fails schema:\n  {e.message}\n  path: {list(e.absolute_path)}")
    else:
        sys.stderr.write(
            "kaizen karpathy loader: jsonschema not installed — validation skipped\n"
        )
    return data

def _principle(data: dict, pid: str) -> dict:
    for p in data.get("principles", []):
        if p.get("id") == pid:
            return p
    _die(f"unknown principle id: {pid}")
    return {}  # unreachable

def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    cmd = argv[0]
    data = load_principles()
    if cmd == "validate":
        print("principles.yaml: valid")
        return 0
    if cmd == "list":
        for p in data.get("principles", []):
            print(p["id"])
        return 0
    if cmd == "principle":
        if len(argv) < 2:
            _die("principle <id> requires an id arg")
        print(json.dumps(_principle(data, argv[1]), indent=2))
        return 0
    if cmd == "scanners":
        scanners = {p.get("scanner") for p in data.get("principles", []) if p.get("scanner")}
        for s in sorted(scanners):
            print(s)
        return 0
    _die(f"unknown command: {cmd}")
    return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
