"""kaizen self-audit core — Finding dataclass + pipeline yaml loader.

Pure primitives consumed by self_audit.py. No I/O beyond reading the
domain yaml + scanning the plugin tree. The Node+Flow runner in
self_audit.py composes these into a pipeline; mechanical checks emit
Findings directly, skill stages emit checkpoint Findings.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent  # plugins/kaizen
REPO_ROOT = PLUGIN_ROOT.parent.parent           # kaizen-md repo
DOMAIN_DIR = PLUGIN_ROOT / "skills" / "plugin-self-audit" / "domain"


# Severity ordering matches audit-pipeline.yaml::severity_order
SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")


@dataclasses.dataclass
class Finding:
    """One audit finding. Schema enforced by domain/schemas/finding.schema.json."""

    id: str
    stage: str
    kind: str        # 'mechanical' | 'checkpoint'
    severity: str    # 'info' | 'low' | 'medium' | 'high' | 'critical'
    title: str
    detail: str = ""
    files: list[str] = dataclasses.field(default_factory=list)
    skill: str = ""           # populated for kind='checkpoint'
    rationale: str = ""
    remediation: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def make_id(stage: str, key: str) -> str:
        h = hashlib.sha1(f"{stage}:{key}".encode()).hexdigest()[:8]
        return f"{stage}-{h}"


# ─── Yaml loader (stdlib-friendly with PyYAML preferred) ─────────────


def load_pipeline() -> dict:
    """Load domain/audit-pipeline.yaml. Falls back to a minimal parser
    when PyYAML missing — but the audit pipeline yaml is small enough
    that PyYAML is strongly preferred."""
    p = DOMAIN_DIR / "audit-pipeline.yaml"
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        # The audit pipeline file uses multi-line `|` strings + nested
        # lists; the minimal parser in _brain.py would mis-parse them.
        # Surface this as a hard error so the user installs PyYAML.
        raise RuntimeError(
            "self-audit requires PyYAML (`pip install pyyaml`); "
            "the pipeline yaml uses multi-line strings the minimal "
            "parser doesn't handle."
        )


# ─── Plugin tree helpers ─────────────────────────────────────────────


def list_skills() -> list[Path]:
    """Every skill dir (vendored + original)."""
    out = []
    skills = PLUGIN_ROOT / "skills"
    if not skills.is_dir():
        return out
    for p in sorted(skills.iterdir()):
        if p.is_dir() and (p / "SKILL.md").is_file():
            out.append(p)
    return out


def list_bin_wrappers() -> list[Path]:
    bin_dir = PLUGIN_ROOT / "bin"
    if not bin_dir.is_dir():
        return []
    return sorted(p for p in bin_dir.iterdir() if p.is_file())


def list_hook_scripts() -> list[Path]:
    hooks = PLUGIN_ROOT / "hooks" / "claude"
    if not hooks.is_dir():
        return []
    return sorted(p for p in hooks.glob("*.sh") if p.is_file())


def list_python_scripts() -> list[Path]:
    scripts = PLUGIN_ROOT / "skills" / "workflow" / "scripts"
    if not scripts.is_dir():
        return []
    return sorted(p for p in scripts.glob("*.py") if p.is_file())


def read_plugin_manifest_text() -> str:
    p = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def read_hooks_json_text() -> str:
    p = PLUGIN_ROOT / "hooks" / "hooks.json"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# ─── Mechanical check helpers ────────────────────────────────────────


def script_underscore_main(script_path: Path) -> bool:
    """Does this Python script have an argparse main()? Quick text probe."""
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "if __name__" in text and ("argparse" in text or "ArgumentParser" in text)


def script_referenced_in_bin(script_name: str) -> Optional[str]:
    """Return the bin wrapper that execs `script_name`, or None."""
    for b in list_bin_wrappers():
        try:
            text = b.read_text(encoding="utf-8")
        except OSError:
            continue
        if script_name in text:
            return b.name
    return None


def script_in_plugin_permissions(script_name: str) -> bool:
    """Check whether the plugin.json::permissions allow-list contains
    a Bash entry for this script (either explicit or via wildcard)."""
    text = read_plugin_manifest_text()
    if not text:
        return False
    if script_name in text:
        return True
    # Wildcard catch-all: skills/workflow/scripts/*.py
    return "skills/workflow/scripts/*.py" in text


def hook_fires_trace(hook_path: Path) -> bool:
    try:
        text = hook_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return ("_trace.sh" in text) or ("trace.py event" in text)


def file_contains_volatile(text: str) -> list[str]:
    """Return list of volatile-data hits (commit shas, ISO dates, LOC counts).
    Defines 'volatile' loosely — false positives acceptable; the user reviews."""
    hits: list[str] = []
    if re.search(r"\b[a-f0-9]{7,40}\b", text):
        # Possible commit SHA — likely false-positive on hex strings; flag for review
        if "commit" in text.lower() or re.search(r"sha[: ]", text, re.IGNORECASE):
            hits.append("commit-sha-like reference")
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", text):
        # Bare ISO date
        if "today" not in text.lower():
            hits.append("ISO date in rulebook")
    return hits


# ─── Vendored skill list (matches plugin-development/scripts/validate.py) ──


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
