"""Memory-entry schema validator (Phase E).

Validates the frontmatter of brain Notes, brain Inbox drafts, and
project-memory entries against
``schemas/brain/schemas/memory-entry.schema.json``.

Stdlib-only — implements just the subset of JSON Schema we use
(required / type / enum / minLength / maxLength / minimum / maximum /
items.type). No ``jsonschema`` dependency (kaizen's heavy-dep policy:
heavy deps lazy-load + graceful-fallback).

## Public surface

- ``validate(fm: dict) -> list[str]`` — schema check on a parsed dict.
- ``validate_text(text: str) -> list[str]`` — split frontmatter from
  body, parse YAML, validate.

Both return ``[]`` on pass; a list of human-readable error strings on
fail (caller decides whether to raise, warn, or surface via the
brain-drift gate).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = (_SCRIPT_DIR.parent.parent / "schemas" / "brain" /
                "schemas" / "memory-entry.schema.json")

_SCHEMA_CACHE: dict | None = None

def _load_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE

# ─── Minimal JSON Schema validator ───────────────────────────────────

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}

def _check_type(value: Any, expected: str) -> bool:
    py = _TYPE_MAP.get(expected)
    if py is None:
        return True  # unknown type → skip (graceful)
    # JSON Schema: integer is NOT a number subtype here — but bool is int in Python; exclude
    if expected == "integer" and isinstance(value, bool):
        return False
    if expected == "number" and isinstance(value, bool):
        return False
    # PyYAML auto-coerces bare `YYYY-MM-DD` to datetime.date. The schema
    # represents these as strings (we serialize them back as ISO dates
    # on write). Accept date/datetime where strings are expected.
    if expected == "string":
        import datetime as _dt
        if isinstance(value, (_dt.date, _dt.datetime)):
            return True
    return isinstance(value, py)

def _validate_one(name: str, value: Any, prop_schema: dict) -> list[str]:
    errors: list[str] = []
    t = prop_schema.get("type")
    if t and not _check_type(value, t):
        errors.append(f"{name}: expected type {t!r}, got "
                      f"{type(value).__name__}")
        return errors  # type wrong → don't bother with rest
    if "enum" in prop_schema and value not in prop_schema["enum"]:
        errors.append(f"{name}: value {value!r} not in enum "
                      f"{prop_schema['enum']}")
    if t == "string":
        if "minLength" in prop_schema and len(value) < prop_schema["minLength"]:
            errors.append(f"{name}: too short ({len(value)} < "
                          f"{prop_schema['minLength']})")
        if "maxLength" in prop_schema and len(value) > prop_schema["maxLength"]:
            errors.append(f"{name}: too long ({len(value)} > "
                          f"{prop_schema['maxLength']})")
    if t in ("integer", "number"):
        if "minimum" in prop_schema and value < prop_schema["minimum"]:
            errors.append(f"{name}: below minimum "
                          f"({value} < {prop_schema['minimum']})")
        if "maximum" in prop_schema and value > prop_schema["maximum"]:
            errors.append(f"{name}: above maximum "
                          f"({value} > {prop_schema['maximum']})")
    if t == "array":
        items_schema = prop_schema.get("items")
        if items_schema:
            item_t = items_schema.get("type")
            for i, item in enumerate(value):
                if item_t and not _check_type(item, item_t):
                    errors.append(f"{name}[{i}]: expected {item_t!r}, "
                                  f"got {type(item).__name__}")
    return errors

def validate(fm: dict) -> list[str]:
    """Validate a parsed frontmatter dict against the memory-entry schema.

    Returns empty list on pass; list of error strings on fail.
    """
    schema = _load_schema()
    errors: list[str] = []
    # Required
    for req in schema.get("required", []):
        if req not in fm:
            errors.append(f"missing required field: {req!r}")
    # Per-property checks
    for name, prop_schema in schema.get("properties", {}).items():
        if name in fm:
            errors.extend(_validate_one(name, fm[name], prop_schema))
    return errors

# ─── Frontmatter extraction + parse ──────────────────────────────────

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)

def _parse_yaml_frontmatter(text: str) -> tuple[dict, list[str]]:
    """Extract + YAML-parse the frontmatter block. Returns (dict, errors).

    Uses PyYAML when available; falls back to a regex line-parser that
    handles the subset of YAML kaizen captures actually produce
    (key: value lines, single-quoted strings, simple lists).
    """
    m = _FM_RE.match(text)
    if not m:
        return {}, ["no frontmatter found (file must start with `---`)"]
    body = m.group(1)
    try:
        import yaml
    except ImportError:
        return _fallback_parse(body)
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as e:
        return {}, [f"malformed YAML frontmatter: {e}"]
    if not isinstance(data, dict):
        return {}, [f"frontmatter must be a mapping, got {type(data).__name__}"]
    return data, []

def _fallback_parse(body: str) -> tuple[dict, list[str]]:
    """No-PyYAML fallback: parse 'key: value' lines only. Lossy but
    sufficient for required+enum checks on well-formed captures.
    """
    out: dict = {}
    for line in body.splitlines():
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
            out[key] = raw[1:-1].replace("''", "'")
        elif raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            try:
                out[key] = json.loads(raw)
            except json.JSONDecodeError:
                out[key] = raw[1:-1]
        elif raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            out[key] = ([s.strip().strip("'\"")
                         for s in inner.split(",")] if inner else [])
        else:
            try:
                out[key] = int(raw)
            except ValueError:
                try:
                    out[key] = float(raw)
                except ValueError:
                    out[key] = raw
    return out, []

def validate_text(text: str) -> list[str]:
    """Parse + validate frontmatter from a full .md file body."""
    fm, errors = _parse_yaml_frontmatter(text)
    if errors:
        return errors
    return validate(fm)
