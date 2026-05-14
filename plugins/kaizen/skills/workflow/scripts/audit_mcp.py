#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp>=1.0",
# ]
# ///
"""kaizen audit-mcp — programmatic access to kaizen-audit reports.

Wraps the existing `kaizen-audit` shell + the audit reports it writes
to `<repo>/.kaizen/workflow/audits/<UTC>-<scope>.md`. Lets Claude run
audits + query findings by severity without grep-ing through the
markdown files manually.

## Tools

  audit_run(scope="", agent=False)
    Run a fresh kaizen-audit. Writes a report to .kaizen/workflow/audits/.
    Returns the report's path + parsed top-level summary.

  audit_list()
    List existing audit reports. Returns newest-first.

  audit_latest()
    Path + parsed summary of the most-recent report.

  audit_read(name)
    Full markdown content of a specific report.

  audit_findings(severity="", scope="")
    Parsed findings from the latest report, optionally filtered by
    severity (CRITICAL / HIGH / MEDIUM / LOW / INFO).

## State

Reports live at `<cwd>/.kaizen/workflow/audits/`. The MCP server inherits
cwd from the project that spawned it.

## Spawning

Registered in .mcp.json as `audit`. CC spawns on first
`mcp__plugin_kaizen_audit__*` invocation.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(
        f"kaizen-audit-mcp: missing dep: {e}\n"
        "Ensure mcp>=1.0 is installed (uv handles this automatically).\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-audit")


# ─── Path resolution ─────────────────────────────────────────────────


def _audits_dir() -> Path:
    """`<repo>/.kaizen/workflow/audits/` — same path the shell script writes to."""
    env = os.environ.get("KAIZEN_AUDITS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd() / ".kaizen" / "workflow" / "audits"


def _audit_sh() -> Path:
    """Resolve the audit.sh script. CLAUDE_PLUGIN_ROOT is set by CC; we
    fall back to deriving from this file's location for non-CC hosts."""
    env = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("KAIZEN_PLUGIN_ROOT")
    if env:
        return Path(env) / "skills" / "workflow" / "scripts" / "audit.sh"
    return SCRIPT_DIR / "audit.sh"


# ─── Report parsing ──────────────────────────────────────────────────


_SEVERITY_H2 = re.compile(
    r"^##\s+(CRITICAL|HIGH|MEDIUM|LOW|INFO)\s*(?:—|--|-)?\s*(\d+)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BULLET = re.compile(r"^\s*-\s+(.+?)$", re.MULTILINE)
_SCOPE_LINE = re.compile(r"^\*\*Scope:\*\*\s*(.+?)$", re.MULTILINE)
_TOTAL_LINE = re.compile(r"^\*\*Total findings:\*\*\s*(\d+)", re.MULTILINE)


def parse_report(text: str) -> dict:
    """Return {scope, total, findings: [{severity, text}, ...]}.

    Robust to extra prose between sections — only counts bullets that
    appear under a recognized severity H2."""
    scope_m = _SCOPE_LINE.search(text)
    scope = scope_m.group(1).strip() if scope_m else ""
    total_m = _TOTAL_LINE.search(text)
    total = int(total_m.group(1)) if total_m else 0

    findings: list[dict] = []
    # Walk the doc collecting (severity, [bullets]) pairs.
    matches = list(_SEVERITY_H2.finditer(text))
    for i, m in enumerate(matches):
        severity = m.group(1).upper()
        section_start = m.end()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[section_start:section_end]
        # Stop at the next H2/H1 / hr to avoid spilling
        terminator = re.search(r"^---\s*$|^##? ", section, re.MULTILINE)
        if terminator:
            section = section[:terminator.start()]
        for b in _BULLET.finditer(section):
            findings.append({"severity": severity, "text": b.group(1).strip()})
    return {"scope": scope, "total": total, "findings": findings}


def _list_reports() -> list[Path]:
    """All audit reports in audit dir, sorted newest-first."""
    d = _audits_dir()
    if not d.is_dir():
        return []
    reports = [p for p in d.iterdir() if p.is_file() and p.suffix == ".md"]
    # Filenames are <UTC>-<scope>.md — lexical sort = chronological
    reports.sort(reverse=True)
    return reports


# ─── MCP tools ───────────────────────────────────────────────────────


@mcp.tool()
async def audit_run(scope: str = "", agent: bool = False) -> dict:
    """Run a fresh kaizen-audit and return the resulting report's path
    plus parsed summary.

    scope: subdir to audit (default: whole repo).
    agent: when True, dispatch agent-aegis + kaizen-debt-auditor in
           parallel (slower, deeper findings).

    The shell script writes its own report; this tool runs the shell,
    waits, then parses the newest file."""
    script = _audit_sh()
    if not script.is_file():
        return {"error": f"audit.sh not found at {script}"}
    args = ["bash", str(script)]
    if scope:
        args.extend(["--scope", scope])
    if agent:
        args.append("--agent")
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"error": "audit.sh exceeded 300s timeout"}
    if result.returncode != 0:
        return {
            "error": f"audit.sh exited {result.returncode}",
            "stderr_tail": result.stderr.splitlines()[-10:],
        }
    reports = _list_reports()
    if not reports:
        return {
            "ran": True,
            "stdout_tail": result.stdout.splitlines()[-10:],
            "warning": "audit ran but no report file found",
        }
    latest = reports[0]
    parsed = parse_report(latest.read_text())
    return {
        "ran": True,
        "report_path": str(latest),
        "scope": parsed["scope"],
        "total": parsed["total"],
        "by_severity": _count_by_severity(parsed["findings"]),
    }


@mcp.tool()
async def audit_list() -> list[dict]:
    """List existing audit reports, newest first. Returns
    [{name, path, mtime}, ...]."""
    import datetime as dt
    out = []
    for p in _list_reports():
        stat = p.stat()
        out.append({
            "name": p.name,
            "path": str(p),
            "mtime": dt.datetime.fromtimestamp(
                stat.st_mtime, dt.timezone.utc
            ).isoformat(),
            "size_bytes": stat.st_size,
        })
    return out


@mcp.tool()
async def audit_latest() -> dict:
    """Most-recent audit report — path + parsed summary."""
    reports = _list_reports()
    if not reports:
        return {"present": False, "audits_dir": str(_audits_dir())}
    latest = reports[0]
    parsed = parse_report(latest.read_text())
    return {
        "present": True,
        "name": latest.name,
        "path": str(latest),
        "scope": parsed["scope"],
        "total": parsed["total"],
        "by_severity": _count_by_severity(parsed["findings"]),
    }


@mcp.tool()
async def audit_read(name: str) -> dict:
    """Full markdown body of a specific report. `name` is the filename
    from audit_list (e.g. '2026-05-13T18-56-59Z-repo.md')."""
    p = _audits_dir() / name
    if not p.is_file():
        # Allow absolute or relative-with-dirs too
        alt = Path(name)
        if not alt.is_file():
            return {"error": f"report not found: {name}", "checked": [str(p), str(alt)]}
        p = alt
    text = p.read_text()
    parsed = parse_report(text)
    return {
        "name": p.name,
        "path": str(p),
        "scope": parsed["scope"],
        "total": parsed["total"],
        "findings": parsed["findings"],
        "body": text,
    }


@mcp.tool()
async def audit_findings(severity: str = "", scope: str = "") -> list[dict]:
    """Findings from the LATEST audit, optionally filtered.

    severity: one of CRITICAL / HIGH / MEDIUM / LOW / INFO (case-insens).
              Empty = all severities.
    scope:    substring filter on the finding text. Empty = all.

    Returns [{severity, text}, ...] in report order."""
    reports = _list_reports()
    if not reports:
        return []
    parsed = parse_report(reports[0].read_text())
    findings = parsed["findings"]
    if severity:
        sev = severity.upper().strip()
        findings = [f for f in findings if f["severity"] == sev]
    if scope:
        findings = [f for f in findings if scope.lower() in f["text"].lower()]
    return findings


def _count_by_severity(findings: list[dict]) -> dict:
    """Counter dict for findings by severity, including zeros."""
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in findings:
        sev = f.get("severity", "").upper()
        if sev in counts:
            counts[sev] += 1
    return counts


if __name__ == "__main__":
    mcp.run()
