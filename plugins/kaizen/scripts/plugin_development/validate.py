#!/usr/bin/env python3
"""kaizen plugin-development validator.

Walks a feature's filesystem footprint and checks it against the
canonical shape in ``../../schemas/plugin-development/feature-shape.yaml``
+ iron laws in ``../../schemas/iron-laws/iron-laws.yaml`` (owned by
the ``iron-laws`` skill) + wiring checklist in
``../../schemas/plugin-development/wiring-checklist.yaml``.

## CLI

::

    python3 validate.py --feature brain          # check one feature
    python3 validate.py --feature brain --json   # machine-readable output
    python3 validate.py --all                    # every kaizen-original feature
    python3 validate.py --staged                 # only features touched by staged diff
    python3 validate.py --laws                   # report on iron-law violations across plugin

## Exit codes

- 0  all checks pass
- 1  soft-severity warnings only
- 2  hard-severity failures (use as a pre-commit gate signal)

## Design

This script is intentionally stdlib-only — no PyYAML required.
The yaml files in ``../domain/`` use a small subset (mappings,
lists, scalars) that a minimal parser handles. Heavy validation
(JSONSchema for manifests, full yaml graph) is optional via
``--strict`` which imports PyYAML + jsonschema when available.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path as _Path

# Envelope: pull from scripts/io/ (canonical post-consolidation sibling).
_IO_DIR = _Path(__file__).resolve().parent.parent / "io"
sys.path.insert(0, str(_IO_DIR))
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-validate", tool_version="1.0.0")
from pathlib import Path
from typing import Any, Optional
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

# Layout (post-migration: scripts/plugin_development/validate.py):
#   SCRIPT_DIR  → plugins/kaizen/scripts/plugin_development/
#   PLUGIN_ROOT → plugins/kaizen/
#   SKILL_DIR   → plugins/kaizen/skills/plugin-development/ (presentation)
#   DOMAIN_DIR  → plugins/kaizen/schemas/plugin-development/ (yaml + schemas
#                 post-consolidation; sibling routine schema.yaml co-located)
#   REPO_ROOT   → kaizen-md repo root
SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent
SKILL_DIR = PLUGIN_ROOT / "skills" / "plugin-development"
DOMAIN_DIR = PLUGIN_ROOT / "schemas" / "plugin-development"
REPO_ROOT = PLUGIN_ROOT.parent.parent   # kaizen-md repo root
# iron-laws.yaml lives with its own skill (skills/iron-laws/).
IRON_LAWS_YAML = PLUGIN_ROOT / "schemas" / "iron-laws" / "iron-laws.yaml"

# ─── Minimal YAML loader (stdlib-only) ───────────────────────────────

def _load_yaml(path: Path) -> dict:
    """Try PyYAML first; fall back to a minimal stdlib parser."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _minimal_parse(text)

def _minimal_parse(text: str) -> dict:
    """Tiny yaml subset — mappings + lists + scalars only."""
    root: dict = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending_list_key: Optional[tuple[int, str]] = None
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        # Pop stack to match indent
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            stack.append((-1, root))
        parent_indent, parent = stack[-1]
        content = line.lstrip()
        if content.startswith("- "):
            # List item
            item_text = content[2:]
            if not isinstance(parent, list):
                continue
            if ":" in item_text and not item_text.startswith(('"', "'")):
                # Inline mapping in list
                item: dict = {}
                key, _, val = item_text.partition(":")
                item[key.strip()] = _scalar(val.strip()) if val.strip() else None
                parent.append(item)
                stack.append((indent, item))
            else:
                parent.append(_scalar(item_text))
        elif ":" in content:
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # Nested
                nested: Any = {}
                if isinstance(parent, dict):
                    parent[key] = nested
                stack.append((indent, nested))
                # Tentatively set as list — corrected when next line is `- `
            elif val.startswith("["):
                # Inline list
                inner = val.strip("[]").strip()
                items = [_scalar(p.strip()) for p in inner.split(",")] if inner else []
                if isinstance(parent, dict):
                    parent[key] = items
            else:
                if isinstance(parent, dict):
                    parent[key] = _scalar(val)
    return _coerce_list_nodes(root)

def _coerce_list_nodes(obj: Any) -> Any:
    """Walk parsed dict; convert dict values to lists when all keys
    are list-item placeholders. The minimal parser starts every
    nested block as a dict; this pass coerces lists-of-mappings."""
    if isinstance(obj, dict):
        # Heuristic: a dict whose ONLY children are dict items that
        # were inserted via `- ` list-item syntax was incorrectly
        # built as a dict. We can't detect this here cleanly; the
        # parser above pushes list-items onto the parent list when
        # the parent IS a list, so as long as the parent was set up
        # right we're OK. Pass through.
        return {k: _coerce_list_nodes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_list_nodes(x) for x in obj]
    return obj

def _scalar(s: str) -> Any:
    s = s.strip()
    if not s:
        return ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() in {"null", "~"}:
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s

# ─── Result types ────────────────────────────────────────────────────

@dataclass
class Finding:
    severity: str       # "hard" | "soft" | "info"
    kind: str            # "missing-slot" | "iron-law" | "wiring"
    feature: str
    message: str
    detail: str = ""

@dataclass
class ValidationReport:
    feature: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def hard_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "hard")

    @property
    def soft_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "soft")

# ─── Feature discovery ───────────────────────────────────────────────

# Vendored skills — never plugin-original, never validated against
# the canonical shape. The list mirrors iron-laws.yaml::no-modify-vendored.
VENDORED_SKILLS = {
    "kiss", "solid", "dry", "yagni", "karpathy", "boy-scout-rule",
    "convention-over-configuration", "law-of-demeter",
    "separation-of-concerns", "brainstorming", "executing-plans",
    "writing-plans", "using-superpowers", "subagent-driven-development",
    "test-driven-development", "verification-before-completion",
    "dispatching-parallel-agents", "finishing-a-development-branch",
    "using-git-worktrees", "writing-skills", "receiving-code-review",
    "requesting-code-review", "systematic-debugging", "tdd",
    "init", "remember", "process", "evolve", "reflect", "synthesize",
    "status",
}

def discover_plugin_features() -> list[str]:
    """List skills that are plugin-original (not vendored)."""
    skills_dir = PLUGIN_ROOT / "skills"
    out = []
    for p in sorted(skills_dir.iterdir()):
        if not p.is_dir():
            continue
        if p.name in VENDORED_SKILLS:
            continue
        if not (p / "SKILL.md").is_file():
            continue
        out.append(p.name)
    return out

def staged_features() -> list[str]:
    """Features touched by the current staged diff. Returns [] when
    not in a git repo or no staged changes."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "diff", "--name-only", "--cached"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    features: set[str] = set()
    plugin_rel = "plugins/kaizen/"
    for line in out.splitlines():
        if not line.startswith(plugin_rel):
            continue
        rest = line[len(plugin_rel):]
        # skills/<feature>/...
        if rest.startswith("skills/"):
            parts = rest.split("/")
            if len(parts) >= 2:
                feat = parts[1]
                if feat not in VENDORED_SKILLS:
                    features.add(feat)
        # scripts/<cluster>/<file>.py — cluster name is the feature
        # post DOMAIN-shells sweep; backing code now lives at
        # plugins/kaizen/scripts/<feature>/ rather than the retired
        # plugins/kaizen/skills/workflow/scripts/ pool.
        if rest.startswith("scripts/"):
            parts = rest.split("/")
            if len(parts) >= 2 and parts[1] and parts[1] != "__pycache__":
                features.add(parts[1])
        # commands/<feature>.md
        if rest.startswith("commands/"):
            cm = rest[len("commands/"):]
            if cm.endswith(".md"):
                features.add(cm[:-3])
        # hooks/claude/<feature>-*.sh
        if rest.startswith("hooks/claude/"):
            hk = rest[len("hooks/claude/"):]
            if hk.endswith(".sh"):
                feat = hk.split("-", 1)[0]
                features.add(feat)
        # bin/kaizen-<feature>
        if rest.startswith("bin/kaizen-"):
            bn = rest[len("bin/kaizen-"):]
            feat = bn.split("-", 1)[0]
            features.add(feat)
    # Cull features that don't actually exist as skill dirs
    discovered = set(discover_plugin_features())
    return sorted(f for f in features if f in discovered)

# ─── Per-feature shape validation ────────────────────────────────────

@dataclass
class FeatureManifest:
    name: str
    predicates: dict[str, bool] = field(default_factory=dict)
    ops: list[str] = field(default_factory=list)

def _scripts_dirs() -> list[Path]:
    """All canonical scripts/<cluster>/ dirs to scan for backing code.

    Post DOMAIN-shells sweep, plugin-original .py files live under
    plugins/kaizen/scripts/<cluster>/ rather than the retired
    skills/workflow/scripts/ shim collection.
    """
    root = PLUGIN_ROOT / "scripts"
    if not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"]


def _any_file(name: str) -> bool:
    """True iff `name` exists in any scripts/<cluster>/ dir."""
    return any((d / name).is_file() for d in _scripts_dirs())


def _any_glob(pattern: str) -> bool:
    """True iff any scripts/<cluster>/ dir has a glob match for `pattern`."""
    return any(any(d.glob(pattern)) for d in _scripts_dirs())


def _glob_all(pattern: str):
    """Iterator over every glob match across scripts/<cluster>/ dirs."""
    for d in _scripts_dirs():
        yield from d.glob(pattern)


def load_or_infer_manifest(feature: str) -> FeatureManifest:
    """Read skills/<feature>/domain/manifest.yaml if present; else
    infer the predicates from filesystem presence."""
    manifest_path = PLUGIN_ROOT / "skills" / feature / "domain" / "manifest.yaml"
    if manifest_path.is_file():
        data = _load_yaml(manifest_path)
        return FeatureManifest(
            name=data.get("name", feature),
            predicates=data.get("predicates", {}) or {},
            ops=data.get("ops", []) or [],
        )

    # Infer from filesystem
    skill_dir = PLUGIN_ROOT / "skills" / feature
    # Backing code: any python script in scripts/<cluster>/ matching the
    # feature name (with or without underscore prefix, with or without
    # an _<op> suffix).
    has_backing_code = (
        _any_file(f"_{feature}.py")
        or _any_file(f"{feature}.py")
        or _any_glob(f"{feature}_*.py")
    )
    # Core/public split: only true when the feature ships a
    # <feature>.py public CLI OR a _<feature>.py private core. MCP-only
    # (audit), op-modules-only (loop), and the host skill (workflow)
    # have backing code but no split — the `core` + `tests` slots
    # don't apply to them.
    has_core_split = (
        _any_file(f"_{feature}.py")
        or _any_file(f"{feature}.py")
    )
    predicates = {
        "feature_has_backing_code": has_backing_code,
        "feature_has_core_split": has_core_split,
        "feature_has_routing_or_taxonomy": any((skill_dir / "domain").glob("*.yaml")) if (skill_dir / "domain").is_dir() else False,
        "feature_writes_validatable_artifacts": (skill_dir / "domain" / "schemas").is_dir() and any((skill_dir / "domain" / "schemas").glob("*.schema.json")),
        "feature_has_skill_scoped_tooling": (skill_dir / "scripts").is_dir() and any((skill_dir / "scripts").glob("*.py")),
        "feature_exposes_cli": _any_file(f"{feature}.py"),
        "feature_needs_search": _any_file(f"{feature}_index.py"),
        "feature_has_multiple_ops": False,  # set below
        "feature_exposes_mcp": _any_file(f"{feature}_mcp.py"),
        "feature_uses_lifecycle_events": any((PLUGIN_ROOT / "hooks" / "claude").glob(f"{feature}-*.sh")),
    }
    # Detect multi-op
    ops = []
    for p in _glob_all(f"{feature}_*.py"):
        suffix = p.stem[len(feature) + 1:]
        if suffix and suffix not in {"index", "mcp"}:
            ops.append(suffix)
    predicates["feature_has_multiple_ops"] = len(ops) > 0
    return FeatureManifest(name=feature, predicates=predicates, ops=ops)

def check_feature_shape(feature: str, manifest: FeatureManifest) -> list[Finding]:
    findings: list[Finding] = []
    shape = _load_yaml(DOMAIN_DIR / "feature-shape.yaml")
    slots = shape.get("slots", [])

    skill_dir = PLUGIN_ROOT / "skills" / feature

    for slot in slots:
        if not isinstance(slot, dict):
            continue
        sid = slot.get("id", "")
        required = bool(slot.get("required", False))
        when = slot.get("when")
        applies = required or (when and manifest.predicates.get(when, False))
        if not applies:
            continue
        # Translate pattern to existence check
        pattern = slot.get("path_pattern", "")
        exists = _slot_exists(pattern, feature, manifest)
        if not exists:
            findings.append(Finding(
                severity="hard" if required else "soft",
                kind="missing-slot",
                feature=feature,
                message=f"missing slot: {sid}",
                detail=f"expected {pattern.replace('<feature>', feature)}",
            ))
    return findings

def _slot_exists(pattern: str, feature: str, manifest: FeatureManifest) -> bool:
    """Check whether at least one file matches the slot pattern.

    Substitutions in order:
      <feature>  → feature slug
      <op>       → each op from manifest.ops; match wins on any-of
      *          → glob expansion
    """
    resolved = pattern.replace("<feature>", feature)

    # Per-op expansion: when the pattern carries <op>, the slot is
    # satisfied if ANY of the manifest's ops resolves to a file.
    if "<op>" in resolved:
        for op in manifest.ops:
            op_resolved = resolved.replace("<op>", op)
            if _exists_with_glob(op_resolved):
                return True
        return False

    return _exists_with_glob(resolved)

def _exists_with_glob(resolved: str) -> bool:
    """Existence check that handles literal globs in the resolved path."""
    if "*" in resolved:
        from glob import glob
        full = PLUGIN_ROOT / resolved
        return bool(glob(str(full), recursive=True))
    return (PLUGIN_ROOT / resolved).is_file()

# ─── Iron-law checks (lightweight static analysis) ──────────────────

def check_iron_laws(feature: Optional[str] = None) -> list[Finding]:
    """Delegate to the iron-laws skill's checker — skills/iron-laws/ owns
    the registry + every `check_*` function; this validator just surfaces
    its findings.

    Lazy import so validate.py stays runnable in constrained environments
    (its stdlib-only design): if the iron-laws checker or its PyYAML /
    jsonschema deps are unavailable, iron-law checks are skipped with one
    info finding rather than crashing."""
    try:
        sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "iron-laws"))
        import _iron_laws  # noqa: E402
    except ImportError as e:
        return [Finding(
            severity="info", kind="iron-law", feature="<global>",
            message="iron-law checks skipped — iron-laws checker unavailable",
            detail=str(e))]
    raw = _iron_laws.run_checks(scope="all", repo_root=REPO_ROOT)
    return [
        Finding(
            severity=f.severity, kind="iron-law",
            feature=f.path or "<global>",
            message=f"{f.law_id}: {f.message}",
            detail=f.detail,
        )
        for f in raw
    ]

# ─── CLI ─────────────────────────────────────────────────────────────

def _print_human(reports: list[ValidationReport]) -> None:
    if not reports:
        print("plugin-development validate: no features to check")
        return
    total_hard = sum(r.hard_count for r in reports)
    total_soft = sum(r.soft_count for r in reports)
    for r in reports:
        if not r.findings:
            print(f"  ✓ {r.feature:<28} clean")
            continue
        print(f"  {'✗' if r.hard_count else '∘'} {r.feature:<28} "
              f"{r.hard_count} hard, {r.soft_count} soft")
        for f in r.findings:
            mark = "✗" if f.severity == "hard" else "∘"
            print(f"      {mark} {f.kind}: {f.message}")
            if f.detail:
                print(f"          {f.detail}")
    print(f"\nplugin-development validate: "
          f"{total_hard} hard, {total_soft} soft "
          f"across {len(reports)} feature(s)")

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="plugin-development-validate",
        description="Validate kaizen-plugin-original features against "
                    "the canonical feature shape + iron laws.",
    )
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--feature", help="check a single feature by name")
    g.add_argument("--all", action="store_true", help="check every plugin-original feature")
    g.add_argument("--staged", action="store_true",
                   help="check only features touched by staged diff")
    g.add_argument("--laws", action="store_true",
                   help="run iron-law checks only (no per-feature shape check)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    if args.laws:
        findings = check_iron_laws()
        rep = ValidationReport(feature="<global>", findings=findings)
        reports = [rep]
    else:
        if args.feature:
            features = [args.feature]
        elif args.staged:
            features = staged_features()
        else:
            features = discover_plugin_features()
        reports: list[ValidationReport] = []
        for feat in features:
            manifest = load_or_infer_manifest(feat)
            findings = check_feature_shape(feat, manifest)
            reports.append(ValidationReport(feature=feat, findings=findings))

    if args.json:
        out = [
            {
                "feature": r.feature,
                "hard": r.hard_count,
                "soft": r.soft_count,
                "findings": [
                    {
                        "severity": f.severity, "kind": f.kind,
                        "message": f.message, "detail": f.detail,
                    } for f in r.findings
                ],
            } for r in reports
        ]
        hard_total = sum(r.hard_count for r in reports)
        soft_total = sum(r.soft_count for r in reports)
        verdict = "red" if hard_total else ("yellow" if soft_total else "green")
        _emit(out, verdict=verdict,
              counts={"hard": hard_total, "soft": soft_total,
                      "features": len(reports)})
    else:
        _print_human(reports)

    # Exit code
    if any(r.hard_count for r in reports):
        return 2
    if any(r.soft_count for r in reports):
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
