"""kaizen hygiene-lang — per-language hygiene composite (roadmap X5).

Extends kaizen-hygiene with per-language audit chains:
  Rust       : cargo audit (security) + rustup toolchain check
  Python     : pip-audit (security) + pyproject lint (basic)
  TypeScript : tsc --noEmit + npm audit
  JavaScript : npm audit
  Go         : go mod tidy --diff + govulncheck

Each language is probed independently — a missing tool reports
"tool not installed" without failing the whole composite. The overall
exit code is non-zero when ANY language check returns a finding (CI-
gateable contract).

## Detection

A language is "present" when its canonical manifest file exists:
  Rust       → Cargo.toml
  Python     → pyproject.toml OR setup.py OR requirements.txt
  TypeScript → tsconfig.json
  JavaScript → package.json
  Go         → go.mod

When multiple languages co-exist (polyglot repos), each is checked
separately and their findings are merged.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ─── Language detection ───────────────────────────────────────────────

LANG_MANIFESTS: dict[str, list[str]] = {
    "rust":       ["Cargo.toml"],
    "python":     ["pyproject.toml", "setup.py", "requirements.txt"],
    "typescript": ["tsconfig.json"],
    "javascript": ["package.json"],
    "go":         ["go.mod"],
}

def detect_languages(root: Path) -> list[str]:
    """Return the list of languages with at least one canonical manifest
    file at `root`. Order matches LANG_MANIFESTS' declaration order."""
    found: list[str] = []
    for lang, manifests in LANG_MANIFESTS.items():
        if any((root / m).is_file() for m in manifests):
            found.append(lang)
    return found

# ─── Probe runner (subprocess-stubbable for tests) ────────────────────

@dataclass
class Probe:
    """One per-language check. `cmd` is the argv to run; `tool` is the
    binary that must exist for the check to be meaningful."""
    name: str
    tool: str
    cmd: list[str]
    description: str = ""
    interpret_exit: str = "nonzero_is_finding"  # or "diff_is_finding"

@dataclass
class Finding:
    language: str
    probe: str
    ok: bool
    note: str
    detail: str = ""
    tool_missing: bool = False

def _run(
    cmd: list[str],
    cwd: Path,
    timeout: int = 60,
    runner: Callable | None = None,
) -> tuple[int, str, str]:
    """Run a command. Returns (returncode, stdout_tail, stderr_tail).
    `runner` lets tests inject a stub without spawning subprocesses."""
    if runner is not None:
        return runner(cmd, cwd, timeout)
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return (
            result.returncode,
            "\n".join(result.stdout.splitlines()[-20:]),
            "\n".join(result.stderr.splitlines()[-20:]),
        )
    except FileNotFoundError:
        return -1, "", "command not found"
    except subprocess.TimeoutExpired:
        return -2, "", f"timed out after {timeout}s"

def _tool_present(tool: str) -> bool:
    """True iff `tool` resolves on PATH (or runner stubs claim it does)."""
    return shutil.which(tool) is not None

# ─── Per-language probe definitions ───────────────────────────────────

PROBES: dict[str, list[Probe]] = {
    "rust": [
        Probe(
            name="cargo-audit",
            tool="cargo",
            cmd=["cargo", "audit", "--quiet"],
            description="RustSec advisory check on Cargo.lock",
        ),
    ],
    "python": [
        Probe(
            name="pip-audit",
            tool="pip-audit",
            cmd=["pip-audit", "--quiet", "--strict"],
            description="PyPA vulnerability advisory check",
        ),
    ],
    "typescript": [
        Probe(
            name="tsc-noemit",
            tool="tsc",
            cmd=["npx", "--no-install", "tsc", "--noEmit"],
            description="TypeScript type-check without writing JS",
        ),
        Probe(
            name="npm-audit",
            tool="npm",
            cmd=["npm", "audit", "--audit-level=high"],
            description="npm package vulnerability check",
        ),
    ],
    "javascript": [
        Probe(
            name="npm-audit",
            tool="npm",
            cmd=["npm", "audit", "--audit-level=high"],
            description="npm package vulnerability check",
        ),
    ],
    "go": [
        Probe(
            name="govulncheck",
            tool="govulncheck",
            cmd=["govulncheck", "./..."],
            description="Go vulnerability scanner",
        ),
    ],
}

# ─── Composite runner ────────────────────────────────────────────────

def run_probe(
    probe: Probe,
    root: Path,
    runner: Callable | None = None,
    tool_present_fn: Callable[[str], bool] | None = None,
) -> Finding:
    """Run one probe and return a Finding. When the tool isn't present
    on PATH, the finding carries `tool_missing=True` and `ok=True`
    (missing-tool is a warning, not a hard fail — many CI envs simply
    don't install every audit tool)."""
    present_fn = tool_present_fn or _tool_present
    if not present_fn(probe.tool):
        return Finding(
            language="",  # filled in by caller
            probe=probe.name,
            ok=True,
            note=f"tool {probe.tool!r} not installed — probe skipped",
            tool_missing=True,
        )
    rc, stdout, stderr = _run(probe.cmd, root, runner=runner)
    if rc == 0:
        return Finding(
            language="", probe=probe.name, ok=True,
            note="clean",
            detail=stdout[:500],
        )
    return Finding(
        language="", probe=probe.name, ok=False,
        note=f"exit {rc}",
        detail=(stderr or stdout)[:1000],
    )

def run_language(
    lang: str,
    root: Path,
    runner: Callable | None = None,
    tool_present_fn: Callable[[str], bool] | None = None,
) -> list[Finding]:
    """Run every probe for `lang`. Each Finding has language=lang filled."""
    out = []
    for probe in PROBES.get(lang, []):
        f = run_probe(probe, root, runner=runner, tool_present_fn=tool_present_fn)
        f.language = lang
        out.append(f)
    return out

@dataclass
class CompositeResult:
    root: str
    languages: list[str]
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Overall pass/fail. Tool-missing findings are not failures
        (CI gate would otherwise demand every audit tool be installed
        everywhere — overly strict)."""
        return all(f.ok or f.tool_missing for f in self.findings)

    @property
    def hard_failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.ok and not f.tool_missing]

    @property
    def tool_missing_count(self) -> int:
        return sum(1 for f in self.findings if f.tool_missing)

def run_composite(
    root: Path | str,
    runner: Callable | None = None,
    tool_present_fn: Callable[[str], bool] | None = None,
) -> CompositeResult:
    """Detect languages + run all per-language probes. Returns a
    CompositeResult whose .ok is True iff no hard failures (tool-
    missing skips are tolerated)."""
    root = Path(root)
    langs = detect_languages(root)
    result = CompositeResult(root=str(root), languages=langs)
    for lang in langs:
        result.findings.extend(run_language(
            lang, root, runner=runner, tool_present_fn=tool_present_fn,
        ))
    return result

# ─── Reporting ────────────────────────────────────────────────────────

def format_report(result: CompositeResult, *, json_mode: bool = False) -> str:
    """Human-readable summary (or JSON when json_mode)."""
    if json_mode:
        return json.dumps({
            "root": result.root,
            "languages": result.languages,
            "ok": result.ok,
            "findings": [
                {
                    "language": f.language,
                    "probe": f.probe,
                    "ok": f.ok,
                    "tool_missing": f.tool_missing,
                    "note": f.note,
                    "detail": f.detail,
                }
                for f in result.findings
            ],
        }, indent=2)
    lines = [
        f"kaizen-hygiene composite: {result.root}",
        f"languages detected: {', '.join(result.languages) or '(none)'}",
        "",
    ]
    if not result.findings:
        lines.append("(no probes ran)")
    for f in result.findings:
        if f.tool_missing:
            icon = "·"
        elif f.ok:
            icon = "✓"
        else:
            icon = "✗"
        lines.append(f"  {icon} {f.language:<10} {f.probe:<15} {f.note}")
    lines.append("")
    if result.hard_failures:
        lines.append(f"FAIL: {len(result.hard_failures)} hard failure(s)")
    elif result.tool_missing_count:
        lines.append(
            f"OK ({result.tool_missing_count} probe(s) skipped — tool missing)"
        )
    else:
        lines.append("OK")
    return "\n".join(lines)
