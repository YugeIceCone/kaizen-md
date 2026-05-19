#!/usr/bin/env python3
"""kaizen efficient-tool-use — staged-shell-file anti-pattern scanner.

Applies the 15 scanner-ready entries from `anti-patterns.yaml` (those with
a `detect` regex) to shell files. Returns one Finding per pattern hit.

Used by `skills/workflow/scripts/gatekeeper.py` as one of the unified
gate's sub-gates. Standalone CLI too — `python3 etu_scan.py --staged`
runs against `git diff --cached --name-only` output.

## CLI

    python3 etu_scan.py --staged              # scan staged .sh files
    python3 etu_scan.py --path FILE…          # scan specific files
    python3 etu_scan.py --all                 # scan every .sh under cwd
    python3 etu_scan.py --json                # emit JSON instead of text

## Exit

  0 — no findings
  1 — one or more findings (any severity)
  2 — invocation error
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

_APP_DIR = Path(__file__).resolve().parent


def _load_anti_patterns() -> dict:
    """Explicit file-path loading to avoid module-name collisions with
    other skills that also have `application/_loader.py` (e.g. iron-laws).
    When the unified `gatekeeper.py` runs both gates in the same process,
    sys.path-based imports return the wrong _loader; this avoids that."""
    spec = importlib.util.spec_from_file_location(
        "kaizen_etu_loader", _APP_DIR / "_loader.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load _loader.py from {_APP_DIR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["kaizen_etu_loader"] = module
    spec.loader.exec_module(module)
    return module.load_anti_patterns()


@dataclass
class Finding:
    pattern_id: str
    severity: str  # error | warn | info
    tool: str
    file: str
    line: int
    matched: str
    why_bad: str
    replacement: str


def _staged_shell_files(repo_root: Path) -> list[Path]:
    """List staged files that look like shell scripts."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
            cwd=repo_root,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    paths = []
    for line in out.splitlines():
        p = repo_root / line.strip()
        if p.suffix in (".sh", ".bash"):
            paths.append(p)
        elif p.is_file():
            try:
                first = p.read_text(errors="ignore").splitlines()[0] if p.stat().st_size else ""
                if first.startswith("#!") and ("sh" in first or "bash" in first):
                    paths.append(p)
            except (OSError, IndexError):
                pass
    return [p for p in paths if p.exists()]


def _all_shell_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.sh")
        if ".git" not in p.parts and "node_modules" not in p.parts
    )


def scan_files(
    files: Iterable[Path],
    repo_root: Path | None = None,
) -> list[Finding]:
    """Run all scanner-ready anti-patterns against the given files."""
    patterns = _load_anti_patterns().get("anti_patterns", [])
    compiled = []
    for ap in patterns:
        det = ap.get("detect")
        if not det:
            continue
        try:
            compiled.append((ap, re.compile(det)))
        except re.error as e:
            sys.stderr.write(
                f"etu_scan: skipping pattern {ap.get('id')} — bad regex: {e}\n"
            )

    # `# noqa: etu` suppresses the etu scanner for the next non-comment
    # non-blank line. Looks back up to 5 lines to allow a multi-line
    # justification comment block above the line being suppressed.
    # Mirrors the Python `# noqa` / ESLint `// eslint-disable-line`
    # pattern, extended to multi-line justifications.
    _NOQA_RX = re.compile(r"#\s*noqa\s*:\s*etu\b", re.IGNORECASE)
    _NOQA_LOOKBACK = 5

    def _suppressed(idx: int, lines: list[str]) -> bool:
        """Line at index `idx` (0-based) is suppressed if a `# noqa: etu`
        marker appears within the previous _NOQA_LOOKBACK lines AND every
        intervening line is a comment or blank (no other code between the
        marker and the suppressed line)."""
        if _NOQA_RX.search(lines[idx]):
            return True
        for back in range(1, _NOQA_LOOKBACK + 1):
            prev_idx = idx - back
            if prev_idx < 0:
                break
            prev = lines[prev_idx].strip()
            if _NOQA_RX.search(prev):
                return True
            # If we hit a non-comment non-blank line before finding the
            # marker, the suppression chain is broken.
            if prev and not prev.lstrip().startswith("#"):
                return False
        return False

    findings: list[Finding] = []
    for path in files:
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if repo_root:
            try:
                rel = str(path.resolve().relative_to(repo_root.resolve()))
            except ValueError:
                rel = str(path)
        else:
            rel = str(path)
        lines = text.splitlines()
        for lineno, line in enumerate(lines, 1):
            if _suppressed(lineno - 1, lines):
                continue
            for ap, rx in compiled:
                m = rx.search(line)
                if m:
                    findings.append(
                        Finding(
                            pattern_id=ap["id"],
                            severity=ap["severity"],
                            tool=ap["tool"],
                            file=rel,
                            line=lineno,
                            matched=line.strip()[:200],
                            why_bad=ap["why_bad"],
                            replacement=ap["replacement"],
                        )
                    )
    return findings


def scan_text(text: str, source: str = "<command>") -> list[Finding]:
    """Apply the catalog's `detect` regexes to a plain text string.

    Used by callers that have the text in hand (no file to read) — most
    notably the PreToolUse Bash gate (`scripts/handlers/_bash_gate.py`),
    which scans the about-to-run command string for anti-patterns
    before letting Claude execute it.

    Same `# noqa: etu` suppression semantics as the file scanner —
    a marker on the same line OR within 5 prior non-code lines
    silences the line.
    """
    patterns = _load_anti_patterns().get("anti_patterns", [])
    compiled = []
    for ap in patterns:
        det = ap.get("detect")
        if not det:
            continue
        try:
            compiled.append((ap, re.compile(det)))
        except re.error as e:
            sys.stderr.write(
                f"etu_scan: skipping pattern {ap.get('id')} — bad regex: {e}\n"
            )

    _NOQA_RX_T = re.compile(r"#\s*noqa\s*:\s*etu\b", re.IGNORECASE)
    lines = text.splitlines() or [text]
    findings: list[Finding] = []
    for lineno, line in enumerate(lines, 1):
        if _NOQA_RX_T.search(line):
            continue
        for ap, rx in compiled:
            m = rx.search(line)
            if m:
                findings.append(
                    Finding(
                        pattern_id=ap["id"],
                        severity=ap["severity"],
                        tool=ap["tool"],
                        file=source,
                        line=lineno,
                        matched=line.strip()[:200],
                        why_bad=ap["why_bad"],
                        replacement=ap["replacement"],
                    )
                )
    return findings


def _render_text(findings: list[Finding]) -> str:
    if not findings:
        return "etu_scan: no findings"
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    summary = ", ".join(f"{s}={n}" for s, n in sorted(counts.items()))
    out = [f"etu_scan: {len(findings)} finding(s) ({summary})\n"]
    for f in findings:
        out.append(
            f"  [{f.severity}] {f.file}:{f.line} {f.pattern_id} ({f.tool})\n"
            f"    matched: {f.matched}\n"
            f"    why:     {f.why_bad}\n"
            f"    fix:     {f.replacement}\n"
        )
    return "".join(out)


def _render_json(findings: list[Finding]) -> str:
    return json.dumps([asdict(f) for f in findings], indent=2)


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    want_json = "--json" in argv
    repo_root = Path.cwd()
    try:
        repo_root = Path(
            subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if argv[0] == "--staged":
        files = _staged_shell_files(repo_root)
    elif argv[0] == "--all":
        files = _all_shell_files(repo_root)
    elif argv[0] == "--path":
        files = [Path(a) for a in argv[1:] if a != "--json"]
    else:
        sys.stderr.write(f"etu_scan: unknown mode: {argv[0]}\n")
        return 2

    findings = scan_files(files, repo_root=repo_root)
    if want_json:
        print(_render_json(findings))
    else:
        print(_render_text(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
