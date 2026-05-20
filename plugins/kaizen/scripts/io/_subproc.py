"""kaizen subproc — shared subprocess + git-root subprocess helpers.

Used by lint_mcp.py, state_mcp.py, workflow_mcp.py, and any consumer
that needs git-aware cwd discovery + list-form subprocess execution.

Single source for `_repo_root` + `_run` extracted in the M2 hygiene
pass (was duplicated byte-identical across 3 MCP servers).

## API

    from _subproc import git_repo_root, run

    cwd = git_repo_root()                              # str
    r = run(["ruff", "check", "."])                    # {exit_code, stdout, stderr}
    r = run(["ty", "check"], timeout=180)              # override timeout

Returns dicts with shape `{exit_code: int, stdout: str, stderr: str}`.
Negative exit_code signals tool absence / timeout:
  -1 → subprocess.TimeoutExpired
  -2 → FileNotFoundError (binary not on PATH)

## Why list-form

Subprocess `run(cmd: list[str])` with a list is injection-safe by
construction — no shell parsing, no path concatenation risk. NEVER
use `shell=True` callers.
"""
from __future__ import annotations

import os
import subprocess

def git_repo_root() -> str:
    """Return `git rev-parse --show-toplevel` or os.getcwd() on miss.

    Used by MCP servers to scope subprocess cwd to the active repo
    when CLAUDE_PROJECT_DIR isn't set."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return os.getcwd()

def run(cmd: list[str], cwd: str | None = None, timeout: int = 30) -> dict:
    """List-form subprocess. Returns {exit_code, stdout, stderr}.

    cwd: defaults to git_repo_root() when None.
    timeout: seconds. Generous defaults appropriate for tools like
        `uv run --with ty` cold-starts (set timeout=120-180 in those cases)."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd or git_repo_root(),
            capture_output=True, text=True, timeout=timeout,
        )
        return {"exit_code": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired as e:
        return {"exit_code": -1, "stdout": "", "stderr": f"timeout after {timeout}s: {e}"}
    except FileNotFoundError as e:
        return {"exit_code": -2, "stdout": "", "stderr": f"binary not found: {e}"}
