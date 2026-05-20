#!/usr/bin/env python3
"""iron-laws — domain loader.

Loads + schema-validates `skills/iron-laws/domain/iron-laws.yaml` — the
single source of truth for the kaizen plugin's iron laws. Every other
surface (codegen, the checker, validate.py, the pre-commit gate, the MCP
server) reads the registry through this module; none parse the yaml
directly.

Self-contained: stdlib + PyYAML + jsonschema. Fail-fast — a
schema-invalid registry raises rather than returning partial data.

## CLI

    python3 _loader.py validate    # validate the registry; exit non-zero on error
    python3 _loader.py list        # law ids, one per line
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

# Domain stays at skills/iron-laws/domain/; only the .py adapter migrated.
DOMAIN_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "iron-laws" / "domain"
)
IRON_LAWS_YAML = DOMAIN_DIR / "iron-laws.yaml"
SCHEMA_PATH = DOMAIN_DIR / "schemas" / "iron-law.schema.json"

def _validate(data: dict, schema_path: Path, label: str) -> None:
    """Validate `data` against the JSON Schema. Raises on failure.

    jsonschema is a hard dependency here — the registry is the SSOT and
    must not be loaded unvalidated."""
    import jsonschema  # noqa: PLC0415 — kept local so import errors are obvious

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"{label}: schema validation failed — {e.message}") from e

def load_registry(path: Path | None = None) -> dict:
    """Load + validate the whole registry dict (`{version, laws}`)."""
    p = path or IRON_LAWS_YAML
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    _validate(data, SCHEMA_PATH, p.name)
    return data

def load_laws(path: Path | None = None) -> list[dict]:
    """Return the list of law dicts. Validates first."""
    return load_registry(path).get("laws", [])

def load_laws_by_id(path: Path | None = None) -> dict[str, dict]:
    """Return laws indexed by id."""
    return {law["id"]: law for law in load_laws(path)}

def auto_laws(path: Path | None = None) -> list[dict]:
    """Laws with `enforcement: auto` — the machine-checked subset."""
    return [law for law in load_laws(path) if law["enforcement"] == "auto"]

def manual_laws(path: Path | None = None) -> list[dict]:
    """Laws with `enforcement: manual` — listed + documented, not auto-checked."""
    return [law for law in load_laws(path) if law["enforcement"] == "manual"]

def get_law(law_id: str, path: Path | None = None) -> dict | None:
    return load_laws_by_id(path).get(law_id)

# ─── CLI ─────────────────────────────────────────────────────────────────

def _cli() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0
    cmd = argv[0]
    if cmd == "validate":
        laws = load_laws()
        print(f"ok — {len(laws)} laws")
        return 0
    if cmd == "list":
        for law in load_laws():
            print(law["id"])
        return 0
    sys.stderr.write(f"[iron-laws/_loader] unknown command: {cmd}\n")
    return 2

if __name__ == "__main__":
    sys.exit(_cli())
