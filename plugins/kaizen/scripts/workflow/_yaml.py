"""kaizen YAML + JSON-Schema helpers — shared loader for application/ modules.

Used by `_loader.py`, `route_intent.py`, and any consumer that needs to
parse a domain yaml + validate it against a JSON Schema.

Single source extracted in the H1 hygiene pass (was duplicated byte-
identical across _loader and route_intent).

## API

    from _yaml import load_yaml, load_json, validate

    data = load_yaml(Path("domain/routines.yaml"))
    schema = load_json(Path("domain/schemas/routine.schema.json"))
    validate(data, schema, source="routines.yaml")   # exits 2 on failure

When `jsonschema` is unavailable (constrained CI sandboxes), `validate`
prints a warning to stderr and returns without checking — matches the
pre-H1 behavior of both loaders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("kaizen yaml helper: PyYAML required (pip install pyyaml)\n")
    sys.exit(1)

try:
    from jsonschema import validate as _validate, ValidationError as _ValidationError
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

def load_yaml(path: Path) -> dict:
    """Parse a YAML file into a dict. Returns {} for empty file."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_json(path: Path) -> dict:
    """Parse a JSON file (typically a JSON Schema)."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def validate(data: dict, schema_path: Path, source: str) -> None:
    """Validate `data` against the JSON Schema at `schema_path`.

    On failure: writes a structured error to stderr and `sys.exit(2)`.
    On missing jsonschema dep: writes a warning to stderr and returns.
    `source` is the human-readable name used in error messages."""
    if not _HAS_JSONSCHEMA:
        sys.stderr.write(f"[kaizen] jsonschema not installed; skipping validation of {source}\n")
        return
    schema = load_json(schema_path)
    try:
        _validate(data, schema)
    except _ValidationError as e:
        sys.stderr.write(
            f"[kaizen] {source} failed schema validation:\n"
            f"  {e.message}\n"
            f"  at: {list(e.absolute_path)}\n"
        )
        sys.exit(2)
