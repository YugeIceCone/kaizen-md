#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen lint-mcp — MCP server exposing ruff (lint+format) and ty
(typecheck+explain) as Claude-callable tools. Token-efficient by default.

Pairs with kaizen-state's CLI-wrapping pattern (subprocess + structured
dict returns; no embedding-model deps). Lazy-installs `ty` via `uv run
--with ty` on first call.

## Tools

  ruff_check(path, select, ignore, fix, verbose)        cosine to ruff CLI
  ruff_format(path, check, diff)                        format-check
  ruff_rules(category, top_n)                           list configured rules
  ty_check(path, error_on_warning, python_version, verbose)  type-check
  ty_explain(rule)                                      rule docs (JSON)
  lint_path(path, verbose)                              ruff + ty composite
  lint_changed_files(base_ref, include_untracked,       diff-filtered combo
                      verbose)

## Token-efficiency design

Linter output for a real repo can be 10K+ tokens. Default mode returns a
curated summary: `{total_findings, by_severity, by_rule (top 5),
findings_top_n (top 10)}`. Pass `verbose=True` for the full list. The
curator is `_curate()` — single source of truth for the compression
strategy across both ruff + ty outputs.

## Why list-form subprocess everywhere

`subprocess.run([cmd, args])` with a list of strings is injection-safe by
construction — no shell parsing, no path concatenation risk. NEVER use
`shell=True` in this file.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

try:
    # ty: ignore[unresolved-import]  — ty can't resolve uv-script PEP 723 deps
    # at static-analysis time; the runtime resolves via `uv run --script`.
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-lint-mcp: missing mcp dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("lint")

SCRIPT_DIR = Path(__file__).resolve().parent
# Curator + severity rank are shared with other MCPs — import from sibling.
sys.path.insert(0, str(SCRIPT_DIR))
from _curate import curate as _curate, SEVERITY_RANK  # noqa: E402
from _uv import uv_cmd  # noqa: E402
from _subproc import git_repo_root as _repo_root  # noqa: E402, F401 — M2 dedup
from _subproc import run as _run_base  # noqa: E402


# ─── Subprocess wrapper — lint-MCP variant ────────────────────────────


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> dict:
    """List-form subprocess. timeout=120s default for `uv run --with ty`
    cold-starts (uv resolves + downloads on first call)."""
    return _run_base(cmd, cwd=cwd, timeout=timeout)


# ─── Curator ──────────────────────────────────────────────────────────
# `_curate` and `SEVERITY_RANK` are imported from `_curate.py` above
# (shared with other MCPs to keep the compression shape consistent).


# ─── ruff_check ───────────────────────────────────────────────────────


def _normalize_ruff(raw: list[dict]) -> list[dict]:
    """Normalise ruff's JSON output into the curator's expected shape."""
    out = []
    for r in raw:
        out.append({
            "severity": "error",  # ruff's findings are all "error" severity by convention
            "code": r.get("code", ""),
            "file": r.get("filename", ""),
            "line": (r.get("location") or {}).get("row"),
            "col": (r.get("location") or {}).get("column"),
            "message": r.get("message", ""),
            "fix_available": bool(r.get("fix")),
        })
    return out


@mcp.tool()
async def ruff_check(
    path: str = ".",
    select: str = "",
    ignore: str = "",
    fix: bool = False,
    verbose: bool = False,
    top_n: int = 10,
    severity_min: str = "",
) -> dict:
    """Run `ruff check --output-format=json` and return findings.

    path: file/dir to check (default ".")
    select: comma-separated rule codes/prefixes to enable (e.g. "E,F,W")
    ignore: comma-separated rule codes/prefixes to disable
    fix: if True, apply fixes (mutating!). Default False = lint-only.
    verbose: if True, return the full findings list. Default False = curated.
    top_n: in curated mode, how many full findings to surface.
    severity_min: optional curator filter ("error", "warning", "info").

    Returns curated summary or full findings (verbose=True). Always
    includes `exit_code` so Claude can detect findings (1) vs clean (0)
    vs error (2)."""
    # v1.30.0+: route through `uv run --with ruff` instead of bare `ruff` so
    # we don't hit snap-confined `ruff` binaries that can't read paths
    # outside their AppArmor allowlist (e.g. ~/.claude/).
    cmd = uv_cmd("ruff", ["check", "--output-format=json", "--no-cache"])
    if select:
        cmd += ["--select", select]
    if ignore:
        cmd += ["--ignore", ignore]
    if fix:
        cmd += ["--fix"]
    cmd += [path]

    r = _run(cmd)
    findings: list[dict] = []
    parse_error = None
    if r["stdout"].strip():
        try:
            findings = _normalize_ruff(json.loads(r["stdout"]))
        except json.JSONDecodeError as e:
            parse_error = str(e)

    base = {"exit_code": r["exit_code"], "command": " ".join(cmd)}
    if parse_error:
        base["parse_error"] = parse_error
        base["raw_stdout"] = r["stdout"][:2000]
    if verbose:
        return {**base, "findings": findings}
    return {**base, **_curate(findings, top_n=top_n, severity_min=severity_min)}


# ─── ruff_format ──────────────────────────────────────────────────────


@mcp.tool()
async def ruff_format(path: str = ".", check: bool = True, diff: bool = False) -> dict:
    """Run `ruff format` in check mode (default) or diff mode.

    check: if True, --check (no mutation). Default True.
    diff: if True, --diff (show what would change). Default False.

    Returns {exit_code, would_format: [paths], diff?, raw}.
    Exit codes (per Astral docs): 0=clean, 1=would-reformat (--check),
    2=error."""
    cmd = uv_cmd("ruff", ["format", "--no-cache"])
    if check:
        cmd += ["--check"]
    if diff:
        cmd += ["--diff"]
    cmd += [path]

    r = _run(cmd)
    # Parse "Would reformat: <path>" / "<path>" lines from stdout
    would: list[str] = []
    for line in (r["stdout"] + "\n" + r["stderr"]).splitlines():
        m = re.match(r"^(?:Would reformat:\s*)?(.+\.py)$", line.strip())
        if m and not line.strip().startswith(("---", "+++", "@@")):
            would.append(m.group(1))
    return {
        "exit_code": r["exit_code"],
        "command": " ".join(cmd),
        "would_format": sorted(set(would)),
        "diff_output": r["stdout"] if diff else None,
    }


# ─── ruff_rules ───────────────────────────────────────────────────────


@mcp.tool()
async def ruff_rules(category: str = "", top_n: int = 50) -> dict:
    """List ruff rule definitions. Compact by default.

    category: filter to rule codes starting with this prefix (e.g. "E", "F").
    top_n: cap on returned rules (default 50). Set 0 for unlimited.

    Returns {total, rules: [{code, name, short_msg, linter, fixable}]}."""
    cmd = uv_cmd("ruff", ["rule", "--all", "--output-format=json", "--no-cache"])
    r = _run(cmd)
    if r["exit_code"] != 0:
        return {"error": r["stderr"] or "ruff rule failed", "exit_code": r["exit_code"]}

    try:
        all_rules = json.loads(r["stdout"])
    except json.JSONDecodeError as e:
        return {"error": f"parse_error: {e}", "raw_stdout": r["stdout"][:2000]}

    if category:
        all_rules = [x for x in all_rules if x.get("code", "").startswith(category)]
    total = len(all_rules)
    if top_n > 0:
        all_rules = all_rules[:top_n]
    return {
        "total": total,
        "returned": len(all_rules),
        "truncated": total > len(all_rules),
        "rules": [
            {
                "code": x.get("code"),
                "name": x.get("name"),
                "short_msg": (x.get("explanation") or "").split("\n", 1)[0][:120],
                "linter": x.get("linter"),
                "fixable": x.get("fix") not in (None, "none"),
            }
            for x in all_rules
        ],
    }


# ─── ty_check ─────────────────────────────────────────────────────────


_TY_CONCISE_RE = re.compile(
    # ty concise format: <file>:<line>:<col>: <severity>[<code>] <message>
    # Note: code is adjacent to severity (no `: ` between them); code is optional.
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<severity>error|warning|info|note|hint)"
    r"(?:\[(?P<code>[^\]]+)\])?\s+"
    r"(?P<message>.+)$"
)


def _parse_ty_concise(text: str) -> tuple[list[dict], list[str]]:
    """Parse ty's `--output-format=concise` line format.

    Returns (findings, unparsed_lines). Defensive: any line that doesn't
    match the expected shape goes into unparsed_lines for the caller to
    inspect. Astral has changed line formats before; this fallback
    prevents silent data loss."""
    findings: list[dict] = []
    unparsed: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith(("ty ", "Checked", "warning: ", "info: ", "Found ")):
            continue
        m = _TY_CONCISE_RE.match(line)
        if m:
            findings.append({
                "file": m.group("file"),
                "line": int(m.group("line")),
                "col": int(m.group("col")),
                "severity": m.group("severity"),
                "code": m.group("code") or "",
                "message": m.group("message"),
            })
        else:
            unparsed.append(line)
    return findings, unparsed


@mcp.tool()
async def ty_check(
    path: str = ".",
    error_on_warning: bool = False,
    python_version: str = "",
    verbose: bool = False,
    top_n: int = 10,
    severity_min: str = "",
) -> dict:
    """Run ty type-check via `uv run --with ty -- ty check --output-format=concise`.

    First call may take ~5s while uv resolves + downloads ty. Subsequent
    calls are fast (uv caches the venv).

    path: file/dir to check.
    error_on_warning: pass --error-on-warning so warnings → exit 1.
    python_version: target Python (e.g. "3.12"). Empty = ty's default.
    verbose: if True, full findings + raw_lines. Default False = curated.
    severity_min: curator filter."""
    cmd = uv_cmd("ty", ["check", "--output-format=concise"])
    if error_on_warning:
        cmd += ["--error-on-warning"]
    if python_version:
        cmd += ["--python-version", python_version]
    cmd += [path]

    r = _run(cmd, timeout=180)  # generous for first-time ty install
    text = r["stdout"] + "\n" + r["stderr"]
    findings, unparsed = _parse_ty_concise(text)

    base = {
        "exit_code": r["exit_code"],
        "command": " ".join(cmd),
        "unparsed_line_count": len(unparsed),
    }
    if verbose:
        return {**base, "findings": findings, "unparsed_lines": unparsed[:50]}
    return {**base, **_curate(findings, top_n=top_n, severity_min=severity_min)}


# ─── ty_explain ───────────────────────────────────────────────────────


@mcp.tool()
async def ty_explain(rule: str = "") -> dict:
    """Get ty rule documentation via `ty explain rule [<name>] --output-format=json`.

    rule: a specific rule name (e.g. "division-by-zero"). Empty = all rules."""
    cmd = uv_cmd("ty", ["explain", "rule"])
    if rule:
        cmd += [rule]
    cmd += ["--output-format=json"]

    r = _run(cmd, timeout=120)
    if r["exit_code"] != 0:
        return {"error": r["stderr"] or "ty explain failed", "exit_code": r["exit_code"]}
    try:
        return {"exit_code": 0, "rules": json.loads(r["stdout"])}
    except json.JSONDecodeError as e:
        return {"error": f"parse_error: {e}", "raw_stdout": r["stdout"][:2000]}


# ─── Composite tools ──────────────────────────────────────────────────


def _max_severity(by_sev: dict) -> str:
    if not by_sev:
        return "none"
    return max(by_sev.keys(), key=lambda s: SEVERITY_RANK.get(s, 0))


@mcp.tool()
async def lint_path(path: str, verbose: bool = False, top_n: int = 10) -> dict:
    """Run BOTH ruff_check and ty_check over a path. Composite result.

    Returns:
        {
          ruff: <ruff_check result>,
          ty:   <ty_check result>,
          summary: {
            total_findings: int,    # ruff + ty combined
            max_severity: str,
            ruff_findings: int,
            ty_findings: int,
          }
        }

    Token-efficient by default (curated). Pass verbose=True for full output."""
    ruff_r, ty_r = await asyncio.gather(
        ruff_check(path=path, verbose=verbose, top_n=top_n),
        ty_check(path=path, verbose=verbose, top_n=top_n),
    )
    ruff_n = ruff_r.get("total") or (len(ruff_r.get("findings", [])) if verbose else 0)
    ty_n = ty_r.get("total") or (len(ty_r.get("findings", [])) if verbose else 0)
    combined_sev = {**ruff_r.get("by_severity", {}), **ty_r.get("by_severity", {})}
    return {
        "ruff": ruff_r,
        "ty": ty_r,
        "summary": {
            "total_findings": ruff_n + ty_n,
            "max_severity": _max_severity(combined_sev),
            "ruff_findings": ruff_n,
            "ty_findings": ty_n,
        },
    }


@mcp.tool()
async def lint_changed_files(
    base_ref: str = "HEAD",
    include_untracked: bool = True,
    verbose: bool = False,
) -> dict:
    """Lint only the .py files changed vs <base_ref>. Composite.

    base_ref: git ref to diff against (default HEAD = working tree vs index).
    include_untracked: if True, also include unstaged untracked .py files.

    Returns:
        {
          files: [paths],
          findings: { <path>: {ruff, ty}, ... },
          summary: { files_checked, total_findings, max_severity }
        }

    Falls through to empty result when there are no .py changes."""
    root = _repo_root()
    # Get changed files
    diff_r = _run(["git", "diff", "--name-only", "--diff-filter=AM", base_ref], cwd=root)
    files = [f for f in diff_r["stdout"].splitlines() if f.endswith(".py")]
    if include_untracked:
        untracked_r = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=root)
        files += [f for f in untracked_r["stdout"].splitlines() if f.endswith(".py")]
    files = sorted(set(files))

    if not files:
        return {
            "files": [],
            "findings": {},
            "summary": {"files_checked": 0, "total_findings": 0, "max_severity": "none"},
        }

    # Fan out per file (parallel via asyncio.gather)
    results = await asyncio.gather(*[lint_path(f, verbose=verbose) for f in files])

    findings_by_file = {}
    total = 0
    all_sev: dict[str, int] = {}
    for f, r in zip(files, results):
        findings_by_file[f] = {"ruff": r["ruff"], "ty": r["ty"], "summary": r["summary"]}
        total += r["summary"]["total_findings"]
        for s, c in r["ruff"].get("by_severity", {}).items():
            all_sev[s] = all_sev.get(s, 0) + c
        for s, c in r["ty"].get("by_severity", {}).items():
            all_sev[s] = all_sev.get(s, 0) + c

    return {
        "files": files,
        "findings": findings_by_file,
        "summary": {
            "files_checked": len(files),
            "total_findings": total,
            "max_severity": _max_severity(all_sev),
            "by_severity": all_sev,
        },
    }


# ─── auto_fix_lint — dispatch fixable findings via subagent / local LLM

@mcp.tool()
async def auto_fix_lint(
    path: str = ".",
    strategy: str = "auto",
    skip_ruff_fixable: bool = True,
    apply: bool = False,
    model: str = "",
    base_ref: str = "",
    remember_choice: bool = False,
) -> dict:
    """Run ruff_check + ty_check, then dispatch remaining findings to a
    fix path via `lint_fix_dispatch.dispatch(...)`.

    strategy:
      'auto'      — DEFAULT. Read the saved per-repo preference (set
                    by a prior call with remember_choice=True). Falls
                    back to 'subagent' when no preference is saved OR
                    the saved 'local_llm' has no reachable server.
      'subagent'  — return structured task specs (one per file). Caller
                    consumes via the Agent tool. No fix is applied.
      'local_llm' — POST each task to LLM_BASE_URL + LLM_MODEL
                    (OpenAI-compatible). If apply=True, the returned
                    unified diff is git-applied. If apply=False, the
                    patch is returned for inspection. When no local
                    server is reachable, returns a 'setup_needed'
                    result with the install script + setup_command —
                    call `lint_fix_setup_local_llm` to run setup.

    skip_ruff_fixable: when True (default), ignore findings ruff --fix
      already handles — those should run via `ruff_check(fix=True)`
      instead of burning LLM tokens.
    base_ref: when set, restrict to files changed vs <base_ref>
      (uses `lint_changed_files`). Empty = lint <path> (default).
    remember_choice: when True, persist the resolved strategy to
      `.kaizen/lint_dispatch_prefs.json` so the next 'auto' call uses
      the same path. The next user doesn't get re-asked.
    """
    # Collect findings using the existing tools
    if base_ref:
        changed = await lint_changed_files(base_ref=base_ref, verbose=True)
        ruff_findings: list[dict] = []
        ty_findings: list[dict] = []
        for file, blob in changed["findings"].items():
            for f in blob.get("ruff", {}).get("findings", []):
                ruff_findings.append({**f, "file": f.get("file") or file})
            for f in blob.get("ty", {}).get("findings", []):
                ty_findings.append({**f, "file": f.get("file") or file})
    else:
        ruff_r = await ruff_check(path=path, verbose=True)
        ty_r   = await ty_check(path=path, verbose=True)
        ruff_findings = ruff_r.get("findings", []) or []
        ty_findings   = ty_r.get("findings", []) or []

    findings = ruff_findings + ty_findings
    if not findings:
        return {
            "strategy": strategy,
            "dispatched_count": 0,
            "skipped_count": 0,
            "tasks": [],
            "note": "no findings",
        }

    # Defer import so kaizen-md plugins without the dispatcher can still
    # import lint_mcp.py (T3 regression).
    sys.path.insert(0, str(Path(__file__).parent))
    import lint_fix_dispatch as _lfd

    root = _repo_root()
    result = _lfd.dispatch(
        findings,
        strategy=strategy,
        repo_root=root,
        skip_ruff_fixable=skip_ruff_fixable,
        model=model or None,
        apply=apply,
    )
    # Persist the resolved strategy when the caller opted in. We never
    # remember "auto" itself — only the concrete subagent | local_llm
    # the auto-resolver picked.
    if remember_choice and result.get("strategy") in ("subagent", "local_llm"):
        try:
            import lint_fix_prefs as _prefs
            _prefs.set_strategy(root, result["strategy"])
            result["remembered"] = True
        except Exception:                                   # noqa: BLE001
            result["remembered"] = False
    return result


# ─── lint_fix_setup_local_llm — surface the setup spec to Claude ─────


@mcp.tool()
async def lint_fix_setup_local_llm() -> dict:
    """Detect whether a local OpenAI-compatible LLM server is reachable
    and, if not, return the install script + one-line setup command.

    Returns the same shape as `lint_fix_setup.setup_summary()`:
      - status='ready' + recommended_url + recommended_model + servers[]
      - status='setup_needed' + install_script + setup_command +
        default_model + default_url

    Side-effect-free — never installs anything itself. The caller
    decides whether to run the install script after user permission.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import lint_fix_setup as _setup
    return _setup.setup_summary()


# ─── Entry point ──────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
