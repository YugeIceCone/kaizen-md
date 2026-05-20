#!/usr/bin/env python3
"""kaizen-axis-runner-rules — pure-fn rule library for axis_runner.

Three dispatcher backends keyed by `scan_spec.type` in axis YAML:

  * `grep`           → `run_grep(pattern, glob, root) → list[dict]`
  * `ast-rule`       → `run_ast_rule(rule, glob, root, params) → list[dict]`
  * `file-coverage`  → `run_file_coverage(expected_glob, actual_glob, root) → list[dict]`

Every fn returns a list of finding dicts with at least `path`. Pure
side-effect-free read-only scan. Importable from `axis_runner.py` and
from tests directly (no envelope wrapping at this layer — kept
composable per onion-DDD inward-only deps).

Refs: /tmp/axis-runner.blueprint.json item-08.4
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# --- grep -------------------------------------------------------------------

def run_grep(pattern: str, glob: str, root: Path | str) -> list[dict]:
    """Scan `root/<glob>` line-by-line; emit `{path,line,match}` for every
    matched line."""
    root = Path(root)
    rx = re.compile(pattern)
    findings: list[dict] = []
    for path in sorted(_iter_glob(root, glob)):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            m = rx.search(line)
            if m:
                rel = _relpath(path, root)
                findings.append({
                    "path": rel,
                    "line": i,
                    "match": m.group(0),
                })
    return findings


# --- ast-rule ---------------------------------------------------------------

_AST_RULES: dict[str, str] = {
    # Reuse exemplar shape from quality/class_name_quality.py + subprocess_rc.py
    "class-camelcase":     "Class names must be CamelCase",
    "subprocess-rc-check": "subprocess.run / call rc must be assigned or check=True",
}


def _ast_rule_class_camelcase(tree: ast.AST, rel_path: str) -> list[dict]:
    rx = re.compile(r"^_?[A-Z][A-Za-z0-9]*$")
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and not rx.match(node.name):
            out.append({"path": rel_path, "line": node.lineno,
                        "rule": "class-camelcase", "name": node.name})
    return out


def _is_subprocess_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id == "subprocess" and f.attr in {
            "run", "call", "check_output", "Popen"
        }
    return False


def _has_check_true(call: ast.Call) -> bool:
    for k in call.keywords:
        if k.arg == "check" and isinstance(k.value, ast.Constant) and k.value.value is True:
            return True
    return False


def _ast_rule_subprocess_rc(tree: ast.AST, rel_path: str) -> list[dict]:
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if _is_subprocess_call(call) and not _has_check_true(call):
                out.append({"path": rel_path, "line": node.lineno,
                            "rule": "subprocess-rc-check",
                            "call": call.func.attr})
    return out


_AST_RULE_IMPLS = {
    "class-camelcase":     _ast_rule_class_camelcase,
    "subprocess-rc-check": _ast_rule_subprocess_rc,
}


def run_ast_rule(rule: str, glob: str, root: Path | str,
                 params: dict | None = None) -> list[dict]:
    """Run a named AST rule across `root/<glob>`. `params` reserved for
    future per-rule tuning; today's two rules ignore params (kept for
    schema-driven extensibility)."""
    del params  # reserved
    root = Path(root)
    impl = _AST_RULE_IMPLS.get(rule)
    if impl is None:
        raise ValueError(
            f"unknown ast-rule: {rule!r}. Available: {sorted(_AST_RULE_IMPLS)}"
        )
    findings: list[dict] = []
    for path in sorted(_iter_glob(root, glob)):
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        findings.extend(impl(tree, _relpath(path, root)))
    return findings


# --- file-coverage ----------------------------------------------------------

def run_file_coverage(expected_glob: str, actual_glob: str,
                      root: Path | str) -> list[dict]:
    """Find files matched by `expected_glob` that lack a stem-matching
    counterpart in `actual_glob` (e.g. `script.py` ↔ `test_script.py`).

    Match heuristic: `stem` of expected file is contained in stem of
    some actual file. Returns one finding per missing pairing."""
    root = Path(root)
    expected = sorted(_iter_glob(root, expected_glob))
    actual = sorted(_iter_glob(root, actual_glob))
    actual_stems = {p.stem for p in actual}
    findings: list[dict] = []
    for ex in expected:
        stem = ex.stem
        # heuristic: counterpart's stem contains expected stem (covers
        # both `name.py` ↔ `test_name.py` and the reverse).
        if not any(stem in a or a in stem for a in actual_stems):
            findings.append({
                "path": _relpath(ex, root),
                "missing": "counterpart",
                "rule": "file-coverage",
            })
    return findings


# --- glob helpers -----------------------------------------------------------

def _iter_glob(root: Path, glob: str):
    """Yield files (not dirs) matching `glob` under `root`. Supports
    both `**/*.py` (recursive) and `docs/*.md` (shallow) — Path.glob
    already handles `**` natively."""
    for p in root.glob(glob):
        if p.is_file():
            yield p


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
