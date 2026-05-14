"""kaizen brain core — schema-driven Second-Brain primitives.

Backs the v1.34+ Python port of the retired remember plugin
(~/.claude/local-marketplaces/remember-md-retired-...). Loads
schema + routing yaml from skills/brain/domain/, provides:

- ``Config``         — paths, types, routing rules
- ``detect_type``    — heuristic classifier (world-fact / belief /
                       observation / experience)
- ``parse_note``     — yaml-frontmatter + markdown body parser
- ``write_note``     — atomic write with frontmatter ordering
- ``select_target`` — applies routing.yaml to pick destination

The capture / promote / audit / evolve flows in brain.py /
brain_promote.py / brain_audit.py / brain_evolve.py compose these
primitives into PocketFlow AsyncNode graphs.

## Brain path resolution

  1. ``$REMEMBER_BRAIN_PATH`` env (legacy compat)
  2. ``$KAIZEN_BRAIN_PATH`` env
  3. ``~/.claude/brain``  (default)

## Project-memory path resolution

  ``~/.claude/projects/<slug>/memory/`` where ``<slug>`` is the
  CC project slug derived from cwd (slashes → dashes, leading
  slash drops).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

# Domain yaml lives one level up (skills/brain/domain/) — resolve
# from the plugin root so tests can run with the source tree.
_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent.parent  # plugins/kaizen
_DOMAIN_DIR = _PLUGIN_ROOT / "skills" / "brain" / "domain"


# ─── TOML / YAML loaders ──────────────────────────────────────────────


def _load_yaml(path: Path) -> dict:
    """Load a YAML file. Prefers stdlib-only path via a tiny parser;
    falls back to PyYAML when available. Brain yaml is small + simple
    so the minimal parser handles it."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _minimal_yaml_parse(text)


def _minimal_yaml_parse(text: str) -> dict:
    """Very small YAML subset — handles the schema files we ship.

    Supports: nested dicts via indent, lists with ``- item``, scalar
    types (str, int, float, bool, null), and quoted strings. Does
    NOT support: anchors, multi-line strings, flow-style, type tags.

    Sufficient for entity-types.yaml + routing.yaml; PyYAML is
    preferred when available (and is in the typical kaizen env).
    """
    lines = text.split("\n")
    return _parse_yaml_block(lines, 0, 0)[0]


def _parse_yaml_block(lines: list[str], start: int, indent: int) -> tuple[dict | list, int]:
    """Parse a block starting at lines[start] with the given indent.
    Returns (parsed, next_line_index)."""
    result: Any = None
    i = start
    while i < len(lines):
        raw = lines[i]
        stripped = raw.split("#", 1)[0].rstrip() if "#" in raw and not raw.lstrip().startswith("#") else raw.rstrip()
        if not stripped.strip():
            i += 1
            continue
        if stripped.lstrip().startswith("#"):
            i += 1
            continue
        cur_indent = len(stripped) - len(stripped.lstrip())
        if cur_indent < indent:
            break
        if cur_indent > indent and result is None:
            i += 1
            continue
        line_text = stripped.lstrip()
        # List item
        if line_text.startswith("- "):
            if result is None:
                result = []
            elif not isinstance(result, list):
                break
            item_text = line_text[2:]
            if ":" in item_text and not item_text.startswith(('"', "'")):
                # Inline mapping start — parse this key + nested keys
                item, i = _parse_yaml_block(["  " * (cur_indent + 1) + item_text] + lines[i + 1:], 0, cur_indent + 2)
                # Adjust i offset
                result.append(item)
                # The recursive call ate one synthetic line; advance once for it.
                i = i  # placeholder; we need different bookkeeping
                # Simpler: parse the inline value as a starter mapping
                # then continue at lines[i+1] with nested keys.
                continue
            else:
                result.append(_parse_yaml_scalar(item_text))
                i += 1
                continue
        # Key: value (mapping)
        if ":" in line_text:
            key, _, val = line_text.partition(":")
            key = key.strip()
            val = val.strip()
            if result is None:
                result = {}
            elif not isinstance(result, dict):
                break
            if val == "":
                # Nested block follows
                nested, i = _parse_yaml_block(lines, i + 1, cur_indent + 2)
                result[key] = nested if nested is not None else {}
            else:
                result[key] = _parse_yaml_scalar(val)
                i += 1
            continue
        i += 1
    return result if result is not None else {}, i


def _parse_yaml_scalar(s: str) -> Any:
    s = s.strip()
    if not s:
        return ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.lower() in {"true", "yes"}:
        return True
    if s.lower() in {"false", "no"}:
        return False
    if s.lower() in {"null", "~", ""}:
        return None
    try:
        if "." not in s:
            return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(p.strip()) for p in inner.split(",")]
    return s


# ─── Path resolution ──────────────────────────────────────────────────


def brain_root() -> Path:
    """Resolve the brain root path.

    Priority: KAIZEN_BRAIN_PATH > REMEMBER_BRAIN_PATH > default.
    KAIZEN_BRAIN_PATH wins so plugin-scoped overrides can shadow a
    user's global REMEMBER_BRAIN_PATH (legacy compat). Handles both
    literal ``$HOME``-style envvar references AND ``~`` expansion."""
    for env in ("KAIZEN_BRAIN_PATH", "REMEMBER_BRAIN_PATH"):
        if env in os.environ and os.environ[env]:
            raw = os.path.expandvars(os.environ[env])
            return Path(raw).expanduser().resolve()
    return Path("~/.claude/brain").expanduser().resolve()


def project_slug_for(cwd: Optional[Path] = None) -> str:
    """Derive the CC project slug from cwd. Slashes → dashes, leading
    slash drops. E.g. ``/home/x/workspace/shodan`` →
    ``-home-x-workspace-shodan``."""
    p = (cwd or Path.cwd()).resolve()
    s = str(p)
    if s.startswith("/"):
        s = "-" + s[1:].replace("/", "-")
    else:
        s = s.replace("/", "-")
    return s


def project_memory_root(cwd: Optional[Path] = None) -> Path:
    """Resolve the project-memory dir for the given cwd."""
    slug = project_slug_for(cwd)
    return Path(f"~/.claude/projects/{slug}/memory").expanduser().resolve()


# ─── Config (loaded from yaml) ────────────────────────────────────────


@dataclass
class TypeSpec:
    name: str
    description: str
    target_dirs: list[str] = field(default_factory=list)
    required_keys: list[str] = field(default_factory=list)
    optional_keys: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)


@dataclass
class TierRule:
    name: str
    when: dict
    route_to: str
    description: str = ""


@dataclass
class FileRule:
    subdir: Optional[str] = None
    filename_template: Optional[str] = None
    when: dict = field(default_factory=dict)


class Config:
    """Loaded schema + routing config."""

    def __init__(
        self,
        types: list[TypeSpec],
        tier_rules: list[TierRule],
        file_rules: dict,
        detection_priority: list[str],
        default_type: str,
        capture_when: list[str],
        skip_when: list[str],
        promotion: dict,
    ):
        self.types = {t.name: t for t in types}
        self.tier_rules = tier_rules
        self.file_rules = file_rules
        self.detection_priority = detection_priority
        self.default_type = default_type
        self.capture_when = capture_when
        self.skip_when = skip_when
        self.promotion = promotion

    @classmethod
    def load(cls, domain_dir: Optional[Path] = None) -> "Config":
        d = domain_dir or _DOMAIN_DIR
        types_data = _load_yaml(d / "entity-types.yaml")
        routing_data = _load_yaml(d / "routing.yaml")

        types = []
        for t in types_data.get("types", []) or []:
            if not isinstance(t, dict):
                continue
            fm = t.get("frontmatter") or {}
            types.append(TypeSpec(
                name=t.get("name", ""),
                description=t.get("description", "") or "",
                target_dirs=list(t.get("target_dirs") or []),
                required_keys=list(fm.get("required") or []),
                optional_keys=list(fm.get("optional") or []),
                triggers=list(t.get("triggers") or []),
            ))

        tier_rules = []
        for r in routing_data.get("tier_rules", []) or []:
            if not isinstance(r, dict):
                continue
            tier_rules.append(TierRule(
                name=r.get("name", ""),
                when=r.get("when") or {},
                route_to=r.get("route_to", ""),
                description=r.get("description", "") or "",
            ))

        file_rules = routing_data.get("file_rules") or {}
        capture = routing_data.get("capture") or {}

        return cls(
            types=types,
            tier_rules=tier_rules,
            file_rules=file_rules,
            detection_priority=list(types_data.get("detection_priority") or [
                "experience", "world-fact", "observation", "belief",
            ]),
            default_type=str(types_data.get("default_type") or "world-fact"),
            capture_when=list(capture.get("capture_when") or []),
            skip_when=list(capture.get("skip_when") or []),
            promotion=routing_data.get("promotion") or {},
        )


# ─── Type detection ───────────────────────────────────────────────────


_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_KEYWORD_RE_CACHE: dict[str, re.Pattern] = {}


def _trigger_to_regex(trigger: str) -> re.Pattern:
    """Compile a trigger string from yaml to a case-insensitive regex.
    Triggers may include glob-like ``.*`` literals (already regex-
    compatible). We just wrap and word-boundary as needed."""
    if trigger not in _KEYWORD_RE_CACHE:
        # Treat the trigger string as case-insensitive substring +
        # support inline `.*` literals authored in the yaml.
        _KEYWORD_RE_CACHE[trigger] = re.compile(trigger, re.IGNORECASE)
    return _KEYWORD_RE_CACHE[trigger]


def detect_type(text: str, cfg: Optional[Config] = None) -> str:
    """Classify a piece of captured text into one of the four types.

    Walks ``cfg.detection_priority`` in order; for each type, tries
    every trigger; first match wins. Falls back to ``cfg.default_type``
    when nothing matches.

    Special cases:
    - ISO date markers (YYYY-MM-DD) → ``experience``
    - "met with" / event verbs → ``experience``
    """
    cfg = cfg or Config.load()
    if not text:
        return cfg.default_type
    # Pre-check for ISO dates → experience (matches the original
    # plugin's special-case handling).
    if _ISO_DATE_RE.search(text):
        if "experience" in cfg.types:
            return "experience"
    for type_name in cfg.detection_priority:
        spec = cfg.types.get(type_name)
        if not spec:
            continue
        for trigger in spec.triggers:
            try:
                if _trigger_to_regex(trigger).search(text):
                    return type_name
            except re.error:
                if trigger.lower() in text.lower():
                    return type_name
    return cfg.default_type


# ─── Frontmatter parse / serialize ────────────────────────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


def parse_note(text: str) -> tuple[dict, str]:
    """Split a brain Note into (frontmatter_dict, body).

    Returns ``({}, full_text)`` when no frontmatter block is found.
    Tolerant of trailing whitespace and missing terminating ``---``.
    """
    if not text:
        return {}, ""
    m = _FRONTMATTER_RE.match(text.lstrip("﻿"))
    if not m:
        return {}, text
    raw_fm, body = m.group(1), m.group(2)
    fm = _parse_frontmatter_block(raw_fm)
    return fm, body


def _parse_frontmatter_block(raw: str) -> dict:
    """Parse a simple key: value frontmatter block (no nested keys).

    Supports lists declared inline (``tags: [a, b, c]``) and YAML-
    style nested dicts shallow (e.g. ``evidence:`` followed by
    ``  - source: ...`` items). Falls back to PyYAML when available
    for the harder cases."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(raw) or {}
    except ImportError:
        pass
    out: dict = {}
    pending_key: Optional[str] = None
    pending_list: Optional[list] = None
    for line in raw.split("\n"):
        if not line.strip():
            continue
        if line.startswith("  -") or line.startswith("\t-"):
            if pending_list is None:
                continue
            pending_list.append(_parse_yaml_scalar(line.split("-", 1)[1].strip()))
            continue
        if ":" in line and not line.startswith(" "):
            if pending_key is not None and pending_list is not None:
                out[pending_key] = pending_list
                pending_list = None
                pending_key = None
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                pending_key = key
                pending_list = []
            else:
                out[key] = _parse_yaml_scalar(val)
                pending_key = None
                pending_list = None
    if pending_key is not None and pending_list is not None:
        out[pending_key] = pending_list
    return out


def serialize_frontmatter(fm: dict) -> str:
    """Render a frontmatter dict to ``---\\n...\\n---\\n``.

    Key order: name, description, type, confidence, tags,
    sources_count, freshness, created, updated, evidence, then any
    remaining keys alphabetical. Matches the convention in existing
    brain Notes."""
    preferred = [
        "name", "description", "type", "confidence", "tags",
        "sources_count", "freshness", "created", "updated", "evidence",
    ]
    ordered_keys = [k for k in preferred if k in fm]
    ordered_keys += sorted(k for k in fm if k not in preferred)
    parts = ["---"]
    for k in ordered_keys:
        v = fm[k]
        parts.append(_render_frontmatter_value(k, v))
    parts.append("---")
    return "\n".join(parts) + "\n"


def _render_frontmatter_value(key: str, val: Any) -> str:
    if isinstance(val, list):
        if all(isinstance(x, (str, int, float, bool)) for x in val):
            if not val:
                return f"{key}: []"
            return f"{key}: [{', '.join(_render_scalar(x) for x in val)}]"
        # Complex list (e.g. evidence) → block form
        lines = [f"{key}:"]
        for item in val:
            if isinstance(item, dict):
                first = True
                for ik, iv in item.items():
                    prefix = "  - " if first else "    "
                    lines.append(f"{prefix}{ik}: {_render_scalar(iv)}")
                    first = False
            else:
                lines.append(f"  - {_render_scalar(item)}")
        return "\n".join(lines)
    return f"{key}: {_render_scalar(val)}"


def _render_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dt.date, dt.datetime)):
        # ISO format — round-trip-compatible with PyYAML's date parse
        return v.isoformat()
    if isinstance(v, str):
        # Quote when string contains special yaml chars
        if any(c in v for c in ":[]{}#&*!|>'\"%@`"):
            return json.dumps(v)
        return v
    return json.dumps(v, default=str)


def write_note(path: Path, fm: dict, body: str) -> None:
    """Atomic write of a Note. Bumps `updated` to today, sets `created`
    if absent. Creates parent dirs."""
    today = dt.date.today().isoformat()
    fm = dict(fm)
    fm.setdefault("created", today)
    fm["updated"] = today
    path.parent.mkdir(parents=True, exist_ok=True)
    content = serialize_frontmatter(fm) + "\n" + body.lstrip("\n")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ─── Slug helpers ─────────────────────────────────────────────────────


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    """Convert free-text to a kebab-case slug suitable for filenames."""
    s = (text or "").lower().strip()
    s = _SLUG_NON_ALNUM.sub("-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "note"


# ─── CLI inspector ────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Inspect kaizen brain core — print resolved paths "
                    "+ detected type for an input string."
    )
    p.add_argument("--text", default="", help="text to classify")
    p.add_argument("--show-config", action="store_true",
                   help="dump loaded config")
    args = p.parse_args()
    cfg = Config.load()
    out = {
        "brain_root": str(brain_root()),
        "project_memory_root": str(project_memory_root()),
        "default_type": cfg.default_type,
        "types": sorted(cfg.types.keys()),
    }
    if args.text:
        out["detected_type"] = detect_type(args.text, cfg)
    if args.show_config:
        out["tier_rules"] = [r.name for r in cfg.tier_rules]
        out["capture_when"] = cfg.capture_when
        out["skip_when"] = cfg.skip_when
    print(json.dumps(out, indent=2))
