#!/usr/bin/env python3
"""kaizen-schema-coverage — audit feature conformance against the four
schema/rubric shapes documented in skills/plugin-development/SKILL.md.

Shapes (per the canonical catalog):
  1. lens-manifest    — domain/<feature>.yaml v2 with subcommands.*.input_schema + output_schema
  2. decision-rubric  — domain/rubric.yaml (or *-rubric.yaml) with `rules`
  3. plain-config     — domain/config.yaml with `version:`
  4. rule-catalog     — domain/<things>.yaml with `version:` + list-of-rule entries

A feature can match ZERO, ONE, or MULTIPLE shapes. Coverage report
surfaces:
  - which shape(s) each feature uses
  - features with `domain/` dirs that match no shape (ad-hoc YAMLs)
  - features writing artifacts without `domain/schemas/*.schema.json`

Stdlib only. CLI:

  schema_coverage.py report [--json]
  schema_coverage.py feature <name> [--json]
  schema_coverage.py gaps [--json]   # only features with conformance gaps
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent


def _plugin_root() -> Path:
    # _SCRIPT_DIR = .../skills/workflow/scripts → parents[2] = plugins/kaizen
    return _SCRIPT_DIR.parents[2]


# ── Shape detectors (pure, regex-only — no PyYAML required) ───────────

_VERSION_RE       = re.compile(r"^version:\s*(\d+)\s*$", re.MULTILINE)
_FEATURE_RE       = re.compile(r"^feature:\s*[\w-]+", re.MULTILINE)
_SUBCOMMANDS_RE   = re.compile(r"^subcommands:\s*$", re.MULTILINE)
_INPUT_SCHEMA_RE  = re.compile(r"input_schema:\s*\S+", re.MULTILINE)
_OUTPUT_SCHEMA_RE = re.compile(r"output_schema:\s*\S+", re.MULTILINE)
_RULES_RE         = re.compile(r"^rules:\s*$", re.MULTILINE)
_REQUIRE_RE       = re.compile(r"require_(all|any):\s*$", re.MULTILINE)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def detect_lens_manifest(domain_dir: Path) -> dict | None:
    """Match shape #1 — Lens manifest v2 (handoff, intent, etc.)."""
    for p in domain_dir.glob("*.yaml"):
        if p.name in ("config.yaml",):
            continue
        text = _read(p)
        if not text:
            continue
        m = _VERSION_RE.search(text)
        has_v2 = m and m.group(1) == "2"
        has_feature = _FEATURE_RE.search(text) is not None
        has_subs = _SUBCOMMANDS_RE.search(text) is not None
        if has_v2 and has_feature and has_subs:
            return {
                "yaml":            str(p.name),
                "has_input_schema":  bool(_INPUT_SCHEMA_RE.search(text)),
                "has_output_schema": bool(_OUTPUT_SCHEMA_RE.search(text)),
            }
    return None


def detect_decision_rubric(domain_dir: Path) -> dict | None:
    """Match shape #2 — rubric.yaml / *-rubric.yaml with `rules:`."""
    candidates = list(domain_dir.glob("rubric.yaml")) + \
                 list(domain_dir.glob("*-rubric.yaml")) + \
                 list(domain_dir.glob("split-rubric.yaml"))
    for p in candidates:
        text = _read(p)
        if not text:
            continue
        if _RULES_RE.search(text):
            return {
                "yaml":            str(p.name),
                "has_require":     bool(_REQUIRE_RE.search(text)),
            }
    return None


def detect_plain_config(domain_dir: Path) -> dict | None:
    """Match shape #3 — config.yaml with `version:`."""
    p = domain_dir / "config.yaml"
    if not p.is_file():
        return None
    text = _read(p)
    if not text or not _VERSION_RE.search(text):
        return None
    return {"yaml": str(p.name)}


def detect_rule_catalog(domain_dir: Path) -> dict | None:
    """Match shape #4 — non-rubric, non-config yaml with `version:` + list entries.

    Heuristic: must have a top-level key followed by `- id:` lines (the
    canonical catalog shape used by intents.yaml / routines.yaml / iron-laws.yaml).
    """
    for p in domain_dir.glob("*.yaml"):
        if p.name in ("config.yaml",) or "rubric" in p.name:
            continue
        text = _read(p)
        if not text:
            continue
        if not _VERSION_RE.search(text):
            continue
        # Look for `- id:` pattern indicating a rule-list shape
        if re.search(r"^\s*-\s+id:\s*\S+", text, re.MULTILINE):
            return {"yaml": str(p.name)}
    return None


def feature_report(feature_dir: Path) -> dict:
    """Build a coverage entry for one skill / feature."""
    domain = feature_dir / "domain"
    schemas_dir = domain / "schemas"
    has_domain = domain.is_dir()
    schemas = sorted(p.name for p in schemas_dir.glob("*.schema.json")) \
              if schemas_dir.is_dir() else []
    yamls = sorted(p.name for p in domain.glob("*.yaml")) \
            if has_domain else []

    shapes: dict[str, dict | None] = {}
    if has_domain:
        shapes["lens-manifest"]   = detect_lens_manifest(domain)
        shapes["decision-rubric"] = detect_decision_rubric(domain)
        shapes["plain-config"]    = detect_plain_config(domain)
        shapes["rule-catalog"]    = detect_rule_catalog(domain)
    else:
        shapes = {k: None for k in
                  ("lens-manifest", "decision-rubric", "plain-config", "rule-catalog")}

    matched = [k for k, v in shapes.items() if v is not None]

    gaps: list[str] = []
    if has_domain and yamls and not matched:
        gaps.append("domain-yaml-no-shape: YAMLs present but match no canonical shape")
    if has_domain and yamls and not schemas:
        gaps.append("no-schemas: domain has YAMLs but no `*.schema.json` validators")
    if shapes.get("lens-manifest"):
        lm = shapes["lens-manifest"]
        if not lm.get("has_input_schema"):
            gaps.append("lens-manifest-no-input-schema")
        if not lm.get("has_output_schema"):
            gaps.append("lens-manifest-no-output-schema")

    return {
        "feature":     feature_dir.name,
        "has_domain":  has_domain,
        "yamls":       yamls,
        "schemas":     schemas,
        "matched_shapes": matched,
        "shapes":      shapes,
        "gaps":        gaps,
        "conformant":  has_domain and bool(matched) and not gaps,
    }


def all_reports(root: Path | None = None) -> list[dict]:
    root = root or _plugin_root()
    skills = root / "skills"
    out = []
    if not skills.is_dir():
        return out
    for p in sorted(skills.iterdir()):
        if not p.is_dir():
            continue
        out.append(feature_report(p))
    return out


def _print_text(reports: list[dict]) -> None:
    with_domain = [r for r in reports if r["has_domain"]]
    conformant = [r for r in with_domain if r["conformant"]]
    with_gaps = [r for r in with_domain if r["gaps"]]
    no_domain = [r for r in reports if not r["has_domain"]]

    print(f"schema-coverage: {len(reports)} feature(s) — "
          f"{len(with_domain)} have domain/, "
          f"{len(conformant)} conformant, "
          f"{len(with_gaps)} with gaps, "
          f"{len(no_domain)} no-domain")
    for r in with_domain:
        shapes = "+".join(r["matched_shapes"]) or "(none)"
        mark = "✓" if r["conformant"] else "△"
        print(f"  {mark} {r['feature']:30s} "
              f"shapes={shapes:35s} "
              f"yamls={len(r['yamls']):>2d} "
              f"schemas={len(r['schemas']):>2d}")
        for g in r["gaps"]:
            print(f"      ⚠ {g}")


def _cmd_report(args) -> int:
    reports = all_reports()
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_text(reports)
    return 0


def _cmd_feature(args) -> int:
    p = _plugin_root() / "skills" / args.name
    if not p.is_dir():
        sys.stderr.write(f"[kaizen-schema-coverage] feature not found: {args.name}\n")
        return 1
    r = feature_report(p)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        _print_text([r])
    return 0


def _cmd_gaps(args) -> int:
    reports = [r for r in all_reports()
               if r["has_domain"] and r["gaps"]]
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_text(reports)
    return 1 if reports else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-schema-coverage",
        description="Audit feature conformance against the 4 schema/rubric shapes.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("report", help="full report (one row per feature)")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=_cmd_report)

    pf = sub.add_parser("feature", help="single-feature report")
    pf.add_argument("name")
    pf.add_argument("--json", action="store_true")
    pf.set_defaults(func=_cmd_feature)

    pg = sub.add_parser("gaps", help="features with conformance gaps (exit 1 if any)")
    pg.add_argument("--json", action="store_true")
    pg.set_defaults(func=_cmd_gaps)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
