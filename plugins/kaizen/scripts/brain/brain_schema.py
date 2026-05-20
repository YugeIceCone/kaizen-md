# consolidated-cli-parent: brain

"""kaizen brain schema — path-inferred frontmatter validate-and-upgrade.

Port of upstream ``remember-md/remember/scripts/schema.js`` —
specifically the ``validateAndUpgrade`` / ``inferExpectedSchema`` /
``applyMissingFrontmatterFields`` / ``appendMissingPersonaSections``
surface that auto-repairs Notes/People/Areas/Projects files missing
required fields, AND ensures Persona.md has Mission/Directives/
Top Beliefs/Evidence Log sections.

Differs from existing kaizen ``_brain.parse_note`` (which just parses)
and the kaizen capture flow (which sets fields at CREATE time but
doesn't repair existing files that drift).

## What it repairs

| Path shape                          | Required fields                                            |
|-------------------------------------|------------------------------------------------------------|
| ``Persona.md``                      | Mission / Directives / Top Beliefs / Evidence Log sections |
| ``Notes/*.md``                      | type=world-fact, freshness=stable, sources_count=1         |
| ``People/*.md``                     | type=observation, last_consolidated, sources_count, freshness |
| ``Areas/*.md``                      | same as People                                             |
| ``Projects/<x>/<x>.md``             | type=observation, …                                        |
| ``Projects/<x>/decisions/*.md``     | type=world-fact, freshness=stable, sources_count=1         |
| ``Projects/<x>/meetings/*.md``      | same as decisions                                          |
| ``Journal/YYYY-MM-DD.md``           | type=experience                                            |

Files outside the brain root → passthrough (no changes).

## Belief-confidence rule

When an L2-typed file declares ``type: belief`` but no ``confidence``,
defaults to 0.5 with a warning emitted in the result dict.

## CLI

::

   kaizen-brain-schema validate <filepath>   # repair-in-place
   kaizen-brain-schema validate --dry-run <filepath>
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))

import _brain  # noqa: E402

# ─── Schema constants (mirror upstream schema.js) ────────────────────


TYPES = {
    "WORLD_FACT": "world-fact",
    "BELIEF": "belief",
    "OBSERVATION": "observation",
    "EXPERIENCE": "experience",
}

FRESHNESS = {
    "STABLE": "stable",
    "STRENGTHENING": "strengthening",
    "WEAKENING": "weakening",
    "STALE": "stale",
    "CONTRADICTED": "contradicted",
}

PERSONA_SECTIONS = ("Mission", "Directives", "Top Beliefs", "Evidence Log")

VALID_TYPES = frozenset(TYPES.values())
VALID_FRESHNESS = frozenset(FRESHNESS.values()) | {"fresh"}  # kaizen extra value

PERSONA_SECTION_PLACEHOLDERS = {
    "Mission": "_to be filled in (Name / Timezone / Languages / Role)_",
    "Directives": ("_Hard rules and explicit preferences. Edit by hand. "
                   "The plugin never overwrites this section._"),
    "Top Beliefs": ("_Auto-managed by brain_rank (runs in the evolve flow). "
                    "Empty until your first belief meets the threshold._"),
    "Evidence Log": "_Append-only behavioural evidence with `[{date}]` prefix._",
}

# ─── Schema inference (path-based) ───────────────────────────────────


def infer_expected_schema(filepath: Path, brain_root: Optional[Path] = None) -> dict:
    """Determine which schema applies to ``filepath`` based on its
    location under ``brain_root``. Mirrors upstream schema.js::
    inferExpectedSchema.

    Returns one of:
      - ``{"kind": "passthrough"}`` — leave the file alone
      - ``{"kind": "persona-sections", "required_sections": (...)}``
      - ``{"kind": "l2-typed", "default_type": "...",
          "required_fields": [...], "defaults": {...}}``
    """
    if brain_root is None:
        return {"kind": "passthrough"}
    abs_path = filepath.resolve()
    root = brain_root.resolve()
    try:
        rel = abs_path.relative_to(root)
    except ValueError:
        return {"kind": "passthrough"}

    rel_str = str(rel)
    parts = rel.parts

    if rel_str == "Persona.md":
        return {"kind": "persona-sections", "required_sections": tuple(PERSONA_SECTIONS)}

    if parts and parts[0] == "Journal" and len(parts) == 2:
        base = parts[1][:-3] if parts[1].endswith(".md") else parts[1]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", base):
            return {
                "kind": "l2-typed",
                "default_type": TYPES["EXPERIENCE"],
                "required_fields": ["type"],
                "defaults": {"type": TYPES["EXPERIENCE"]},
            }
        return {"kind": "passthrough"}

    if parts and parts[0] in ("People", "Areas") and len(parts) == 2:
        return {
            "kind": "l2-typed",
            "default_type": TYPES["OBSERVATION"],
            "required_fields": ["type", "last_consolidated", "sources_count", "freshness"],
            "defaults": {
                "type": TYPES["OBSERVATION"],
                "last_consolidated": "{TODAY}",
                "sources_count": 1,
                "freshness": FRESHNESS["STABLE"],
            },
        }

    if parts and parts[0] == "Projects" and len(parts) >= 3:
        proj_name = parts[1]
        sub_path = "/".join(parts[2:])
        # Projects/<x>/<x>.md
        if sub_path == f"{proj_name}.md":
            return {
                "kind": "l2-typed",
                "default_type": TYPES["OBSERVATION"],
                "required_fields": ["type", "last_consolidated", "sources_count", "freshness"],
                "defaults": {
                    "type": TYPES["OBSERVATION"],
                    "last_consolidated": "{TODAY}",
                    "sources_count": 1,
                    "freshness": FRESHNESS["STABLE"],
                },
            }
        if sub_path.startswith("decisions/") or sub_path.startswith("meetings/"):
            return {
                "kind": "l2-typed",
                "default_type": TYPES["WORLD_FACT"],
                "required_fields": ["type", "freshness", "sources_count"],
                "defaults": {
                    "type": TYPES["WORLD_FACT"],
                    "freshness": FRESHNESS["STABLE"],
                    "sources_count": 1,
                },
            }
        return {"kind": "passthrough"}

    if parts and parts[0] == "Notes" and len(parts) == 2:
        return {
            "kind": "l2-typed",
            "default_type": TYPES["WORLD_FACT"],
            "required_fields": ["type", "freshness", "sources_count"],
            "defaults": {
                "type": TYPES["WORLD_FACT"],
                "freshness": FRESHNESS["STABLE"],
                "sources_count": 1,
            },
        }

    return {"kind": "passthrough"}


# ─── Frontmatter manipulation (text-level, preserves byte layout) ────


_FM_OPEN_RE = re.compile(r"^---\r?\n", re.M)


def _split_frontmatter(text: str) -> tuple[str, str, bool]:
    """Return ``(frontmatter_body, document_body, had_frontmatter)``.

    Strict: matches upstream schema.js::splitFrontmatter semantics
    where missing frontmatter returns the whole text as body."""
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return "", text, False
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", text)
    if not m:
        return "", text, False
    return m.group(1), text[m.end():], True


def _parse_fm_keys(fm_text: str) -> set[str]:
    """Extract top-level keys from the frontmatter block. Mirrors
    upstream schema.js::parseFmKeys (regex-based; ignores nested keys)."""
    keys = set()
    for line in fm_text.split("\n"):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if m:
            keys.add(m.group(1))
    return keys


def _format_yaml_value(v) -> str:
    """Quote scalars that contain YAML-special chars; pass through ints/floats/bools."""
    if isinstance(v, str):
        if v == "" or re.search(r"[:#\[\]&*?{}|>!%@`,]", v):
            return json.dumps(v)
        return v
    if isinstance(v, list):
        if not v:
            return "[]"
        return json.dumps(v)
    if isinstance(v, dict):
        return json.dumps(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def apply_missing_frontmatter_fields(
    text: str, defaults: dict, today: str
) -> dict:
    """Insert missing required fields into the frontmatter block.

    Preserves existing frontmatter byte-for-byte. New fields are
    appended BEFORE the closing ``---``. Substitutes ``{TODAY}``
    placeholder. Returns ``{text, added_fields}``.

    Mirrors upstream schema.js::applyMissingFrontmatterFields."""
    fm, body, had_fm = _split_frontmatter(text)
    existing = _parse_fm_keys(fm)

    additions = []
    added_fields = []
    for k, v in defaults.items():
        if k in existing:
            continue
        value = today if v == "{TODAY}" else v
        additions.append(f"{k}: {_format_yaml_value(value)}")
        added_fields.append(k)

    if not additions:
        return {"text": text, "added_fields": []}

    if had_fm:
        new_fm = f"---\n{fm}\n{chr(10).join(additions)}\n---\n"
        return {"text": new_fm + body, "added_fields": added_fields}

    new_fm = f"---\n{chr(10).join(additions)}\n---\n\n"
    return {"text": new_fm + body, "added_fields": added_fields}


def _find_existing_sections(text: str) -> set[str]:
    """Extract h2 section names from a markdown document."""
    present = set()
    for line in text.split("\n"):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            present.add(m.group(1).strip())
    return present


def append_missing_persona_sections(
    text: str, required_sections: tuple[str, ...]
) -> dict:
    """Ensure Persona has all required ## sections. Missing sections
    are appended at end with placeholder text.

    Mirrors upstream schema.js::appendMissingPersonaSections."""
    present = _find_existing_sections(text)
    missing = [s for s in required_sections if s not in present]
    if not missing:
        return {"text": text, "added_sections": []}

    blocks = [
        f"## {s}\n\n{PERSONA_SECTION_PLACEHOLDERS.get(s, '_…_')}\n"
        for s in missing
    ]
    trimmed = re.sub(r"\s+$", "", text)
    new_text = f"{trimmed}\n\n" + "\n".join(blocks)
    return {"text": new_text, "added_sections": missing}


# ─── Cross-link health (extracted from self_improving/brain_validator) ─


def check_links(brain_root: Path) -> dict:
    """Find every ``[[ref]]`` in Persona.md + Notes/, verify each resolves
    to a real file. Returns ``{refs_count, broken: [(src, ref), ...]}``.

    A ref resolves if any of these exist:
      - <brain>/Notes/<ref-without-md>.md
      - <brain>/<ref-without-md>.md
      - <brain>/<ref> (when ref includes a path segment like 'Journal/...')
    """
    if not brain_root.is_dir():
        return {"refs_count": 0, "broken": []}
    files: list[Path] = []
    persona = brain_root / "Persona.md"
    if persona.is_file():
        files.append(persona)
    notes_dir = brain_root / "Notes"
    if notes_dir.is_dir():
        files.extend(sorted(notes_dir.glob("*.md")))

    refs: list[tuple[Path, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in re.finditer(r"\[\[([A-Za-z0-9/_\-\.]+)\]\]", text):
            refs.append((f, m.group(1)))

    broken: list[tuple[str, str]] = []
    for src, ref in refs:
        name = ref[:-3] if ref.endswith(".md") else ref
        candidates = [
            brain_root / "Notes" / f"{name}.md",
            brain_root / f"{name}.md",
            brain_root / ref,
        ]
        if "/" in name:
            candidates.append(brain_root / f"{name}.md")
        if not any(c.is_file() for c in candidates):
            broken.append((src.name, ref))
    return {"refs_count": len(refs), "broken": broken}


# ─── Public entry point ──────────────────────────────────────────────


def validate_and_upgrade(
    filepath: Path,
    *,
    brain_root: Optional[Path] = None,
    today: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Validate + repair a single file. In-place atomic write when
    changes are needed.

    Returns ``{changed, added_fields, added_sections, warnings}``.
    Mirrors upstream schema.js::validateAndUpgrade.

    Files outside brain → passthrough (no changes, no error).
    Missing files → return blank result (no error).

    ``dry_run=True`` skips the file write — useful for CI gates that
    want to surface schema drift without auto-fixing. ``changed`` still
    reports what WOULD change."""
    today_str = today or _dt.date.today().isoformat()
    result = {"changed": False, "added_fields": [], "added_sections": [], "warnings": []}

    if not filepath.is_file():
        return result

    expected = infer_expected_schema(filepath, brain_root)
    if expected["kind"] == "passthrough":
        return result

    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError:
        return result
    original = text

    if expected["kind"] == "l2-typed":
        upgrade = apply_missing_frontmatter_fields(text, expected["defaults"], today_str)
        text = upgrade["text"]
        result["added_fields"] = list(upgrade["added_fields"])

        # Belief without confidence → default to 0.5 + warning
        fm, _body, _had = _split_frontmatter(text)
        fm_keys = _parse_fm_keys(fm)
        type_match = re.search(r"^type:\s*(\S+)", fm, re.M)
        if (type_match and type_match.group(1) == TYPES["BELIEF"]
                and "confidence" not in fm_keys):
            upgrade2 = apply_missing_frontmatter_fields(
                text, {"confidence": 0.5}, today_str
            )
            text = upgrade2["text"]
            result["added_fields"].extend(upgrade2["added_fields"])
            rel = str(filepath.relative_to(brain_root)) if brain_root else str(filepath)
            result["warnings"].append(f"confidence defaulted to 0.5 — review {rel}")

    elif expected["kind"] == "persona-sections":
        upgrade = append_missing_persona_sections(text, expected["required_sections"])
        text = upgrade["text"]
        result["added_sections"] = list(upgrade["added_sections"])

    if text != original:
        if dry_run:
            result["changed"] = True  # report-would-change without writing
        else:
            # Atomic write: tempfile + rename.
            tmp = filepath.with_suffix(filepath.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(filepath)
            result["changed"] = True

    return result


# ─── CLI ─────────────────────────────────────────────────────────────


def _emit_json(result: dict) -> None:
    sys.stdout.write(json.dumps({
        "data": result,
        "kaizen": {
            "command": "brain_schema.py",
            "tool": "kaizen-brain-schema",
            "tool_version": "1.0.0",
            "schema_version": 1,
        },
    }, default=str, indent=2) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kaizen-brain-schema",
        description="Path-inferred frontmatter validate-and-upgrade.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate + upgrade a file")
    v.add_argument("filepath", type=Path)
    v.add_argument("--brain", type=Path, default=None,
                   help="brain root (default: $KAIZEN_BRAIN_DIR)")
    v.add_argument("--today", default=None,
                   help="override today's date (ISO yyyy-mm-dd)")
    v.add_argument("--dry-run", action="store_true",
                   help="report what would change without writing — CI-gate friendly")
    v.add_argument("--json", action="store_true",
                   help="emit structured envelope on stdout")
    cl = sub.add_parser("check-links",
                        help="audit [[ref]] cross-links across Persona + Notes")
    cl.add_argument("--brain", type=Path, default=None,
                    help="brain root (default: $KAIZEN_BRAIN_DIR)")
    cl.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if os.environ.get("KAIZEN_BRAIN_SCHEMA_DISABLE") == "1":
        sys.stderr.write("kaizen-brain-schema: disabled via KAIZEN_BRAIN_SCHEMA_DISABLE=1\n")
        return 0

    brain = args.brain or _brain.brain_root()

    if args.cmd == "check-links":
        result = check_links(brain)
        if args.json:
            _emit_json(result)
            return 0
        if result["broken"]:
            sys.stdout.write(f"check-links: {len(result['broken'])} broken / "
                             f"{result['refs_count']} refs\n")
            for src, ref in result["broken"][:20]:
                sys.stdout.write(f"  [BROKEN] {src} → [[{ref}]]\n")
            return 2
        sys.stdout.write(f"OK: {result['refs_count']} cross-references resolve\n")
        return 0

    result = validate_and_upgrade(
        args.filepath, brain_root=brain, today=args.today,
        dry_run=getattr(args, "dry_run", False),
    )

    if args.json:
        _emit_json(result)
        return 0

    sys.stdout.write(json.dumps(result, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
