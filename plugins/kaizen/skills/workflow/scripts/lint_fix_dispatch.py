"""lint_fix_dispatch — route ruff/ty findings to a fix path.

Two strategies — both consume the same finding shape that
`lint_mcp._normalize_ruff` and `_parse_ty_concise` already produce:

  strategy='subagent'
      Emit a list of structured task specs (one per file). The caller —
      typically the Claude session running the kaizen workflow — reads
      `result["tasks"]` and dispatches each via its Agent tool. Pure;
      no I/O.

  strategy='local_llm'
      POST one chat-completion request per file group to an OpenAI-
      compatible endpoint (configured via LLM_BASE_URL + LLM_MODEL +
      LLM_API_KEY). Extract a unified diff from the response. If
      `apply=True`, run `git apply --3way` against the repo root.

Both return:
    {
      "strategy":          "subagent" | "local_llm",
      "dispatched_count":  int,
      "skipped_count":     int,     # findings ruff --fix already handles
      "tasks":             list[dict],
    }

Each task dict carries:
    file:        str
    findings:    list[dict]   (the original normalised findings)
    prompt:      str          (ready for Agent tool or LLM body)
    description: str          (short — for Agent tool's `description` field)
    patch?:      str          (local_llm only — extracted unified diff)
    patch_extraction_failed?: bool
    apply_status?: "applied" | "failed" | "skipped"   (local_llm only)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from typing import Any

DEFAULT_ENV_VARS = ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")
_DEFAULT_BASE_URL = "http://127.0.0.1:8080"
_DEFAULT_MODEL = "local"
# "auto" reads the saved per-repo preference (subagent | local_llm) via
# lint_fix_prefs; falls back to subagent when nothing is set or the
# local LLM is unreachable.
_VALID_STRATEGIES = ("subagent", "local_llm", "auto")


# ───────────────────────────────────────────────────────────────────────
# Prompt rendering
# ───────────────────────────────────────────────────────────────────────

_PROMPT_HEADER = """Fix the lint findings in `{file}` below.

Findings (from ruff / ty):
{finding_block}

Rules:
  - Make the SMALLEST change that clears each finding.
  - Preserve the file's existing style and structure.
  - Do NOT add new functionality.
  - Return a unified diff (``` diff ... ```) against `{file}`.

If a finding can't be safely fixed without changing behavior, leave it
and note why in a comment at the top of the diff.
"""


def _finding_line(f: dict) -> str:
    loc = ""
    if f.get("line") is not None:
        loc = f":{f['line']}"
        if f.get("col") is not None:
            loc += f":{f['col']}"
    return f"  - [{f.get('code', '?')}]{loc} {f.get('message', '').strip()}"


def _render_prompt(file: str, findings: list[dict]) -> str:
    return _PROMPT_HEADER.format(
        file=file,
        finding_block="\n".join(_finding_line(f) for f in findings),
    )


def _short_description(file: str, n_findings: int) -> str:
    name = os.path.basename(file) or file
    return f"Fix {n_findings} lint finding(s) in {name}"


# ───────────────────────────────────────────────────────────────────────
# Diff extraction + apply
# ───────────────────────────────────────────────────────────────────────

_FENCED_DIFF = re.compile(r"```(?:diff|patch)?\s*\n(.*?)\n```", re.DOTALL)
_BARE_UNIFIED = re.compile(r"(--- [^\n]+\n\+\+\+ [^\n]+\n.*)", re.DOTALL)


def _extract_diff(text: str) -> str:
    for m in _FENCED_DIFF.finditer(text):
        body = m.group(1).strip()
        if body.startswith("---") or body.startswith("diff "):
            return body
    m = _BARE_UNIFIED.search(text)
    if m:
        return m.group(1).strip()
    return ""


# Scope guard helpers (SEC-3): an LLM-generated diff must touch only
# the file(s) we asked it to fix. Without a scope check a prompt-
# injected lint server could patch `.github/workflows/`, hook scripts,
# `bin/`, or any other path it pleases.

_DIFF_TARGET_RE = re.compile(
    r"^\+\+\+\s+(?:b/)?(\S+)$", re.MULTILINE
)


def _diff_targets(diff: str) -> set[str]:
    """Extract every `+++ b/<path>` target from a unified diff. Strips
    the leading `b/` (git's default prefix). `/dev/null` (deletion
    target) is dropped — that's not a write."""
    targets = set()
    for m in _DIFF_TARGET_RE.finditer(diff):
        path = m.group(1)
        if path == "/dev/null":
            continue
        targets.add(path)
    return targets


def _diff_in_scope(diff: str, allowed_paths: set[str]) -> bool:
    """True iff every target in `diff` is a member of `allowed_paths`.
    Empty target set = vacuously in-scope (nothing to apply)."""
    targets = _diff_targets(diff)
    return targets.issubset(allowed_paths)


def _apply_patch(diff: str, repo_root: str,
                  allowed_paths: set[str] | None = None) -> bool:
    """`git apply --3way --whitespace=nowarn`. Returns True on success.

    SEC-3: when `allowed_paths` is provided, REFUSE if the diff touches
    any path outside the allow-list. Caller passes the set of files
    associated with the lint findings — an LLM that returns a diff
    against any other path gets refused before `git apply` runs.
    """
    if allowed_paths is not None and not _diff_in_scope(diff, allowed_paths):
        targets = _diff_targets(diff)
        rogue = targets - allowed_paths
        print(f"[lint_fix_dispatch] REFUSED: diff targets {sorted(rogue)} "
              f"outside the lint-finding scope {sorted(allowed_paths)}",
              file=sys.stderr)
        return False
    try:
        proc = subprocess.run(
            ["git", "apply", "--3way", "--whitespace=nowarn", "-"],
            input=diff, text=True, capture_output=True,
            cwd=repo_root, timeout=30, check=False,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


# ───────────────────────────────────────────────────────────────────────
# Local LLM HTTP — minimal OpenAI-compatible client
# ───────────────────────────────────────────────────────────────────────

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _http_post(url: str, payload: dict, *, api_key: str | None = None,
                timeout: float = 60.0) -> dict:
    # SEC-4: explicit scheme allowlist (defense-in-depth — urllib will
    # honor file:// / ftp:// otherwise).
    from urllib.parse import urlparse as _urlparse
    if _urlparse(url).scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"refusing non-http(s) URL scheme: {url!r} "
            f"(allowed: {sorted(_ALLOWED_SCHEMES)})"
        )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:        # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _local_llm_call(prompt: str, *, model: str, base_url: str,
                     api_key: str | None) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    url = base_url.rstrip("/") + "/v1/chat/completions"
    resp = _http_post(url, payload, api_key=api_key)
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


# ───────────────────────────────────────────────────────────────────────
# Main entry
# ───────────────────────────────────────────────────────────────────────

def _group_by_file(findings: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        path = f.get("file") or ""
        if not path:
            continue
        groups[path].append(f)
    return groups


def dispatch(
    findings: list[dict],
    *,
    strategy: str,
    repo_root: str,
    skip_ruff_fixable: bool = True,
    model: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Route lint findings to a fix path. See module docstring for
    strategies + return shape.

    strategy='auto' resolves the per-repo preference written by
    `lint_fix_prefs.set_strategy(...)`. When the resolved strategy is
    'local_llm' but no server is reachable (per `lint_fix_setup.
    detect_servers()`), the call falls back to 'subagent' and sets
    `local_llm_fallback=True` in the result.

    strategy='local_llm' explicitly + no server reachable returns
    `{status: 'setup_needed', install_script, setup_command}` so the
    caller can surface the install path to the user rather than burying
    an HTTP error.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(
            f"unknown strategy {strategy!r}; must be one of {_VALID_STRATEGIES}"
        )

    # ─── Resolve auto → subagent | local_llm via saved prefs ───────────
    fallback_from_local_llm = False
    if strategy == "auto":
        try:
            import lint_fix_prefs as _prefs
            resolved = _prefs.get_strategy(repo_root, default="subagent")
        except ImportError:
            resolved = "subagent"
        if resolved == "local_llm":
            # Degrade gracefully when the saved choice is local_llm but
            # the server isn't there right now (user moved hosts, daemon
            # died, etc.) — pick subagent + flag it.
            if not _llm_reachable():
                fallback_from_local_llm = True
                resolved = "subagent"
        strategy = resolved
    elif strategy == "local_llm" and not _llm_reachable():
        # Explicit local_llm + unreachable → don't burn an HTTP error;
        # surface the setup spec so the caller can act.
        try:
            import lint_fix_setup as _setup
            summary = _setup.setup_summary()
        except ImportError:
            summary = {"status": "setup_needed"}
        summary["strategy"] = "local_llm"
        summary["dispatched_count"] = 0
        summary["skipped_count"] = len(findings)
        summary["tasks"] = []
        return summary

    if skip_ruff_fixable:
        kept = [f for f in findings if not f.get("fix_available")]
        skipped = len(findings) - len(kept)
    else:
        kept = list(findings)
        skipped = 0

    groups = _group_by_file(kept)
    tasks: list[dict] = []
    base_url = os.environ.get("LLM_BASE_URL", _DEFAULT_BASE_URL)
    api_key  = os.environ.get("LLM_API_KEY")
    chosen_model = model or os.environ.get("LLM_MODEL", _DEFAULT_MODEL)

    for file, file_findings in sorted(groups.items()):
        prompt = _render_prompt(file, file_findings)
        task: dict[str, Any] = {
            "file": file,
            "findings": file_findings,
            "prompt": prompt,
            "description": _short_description(file, len(file_findings)),
        }
        if strategy == "local_llm":
            content = _local_llm_call(
                prompt, model=chosen_model, base_url=base_url, api_key=api_key,
            )
            diff = _extract_diff(content)
            task["patch"] = diff
            if not diff:
                task["patch_extraction_failed"] = True
                task["apply_status"] = "skipped"
            elif apply:
                # SEC-3: scope the patch to ONLY this finding's file —
                # a prompt-injected LLM can't patch hooks, CI, etc.
                ok = _apply_patch(diff, repo_root, allowed_paths={file})
                task["apply_status"] = "applied" if ok else "failed"
            else:
                task["apply_status"] = "skipped"
        tasks.append(task)

    result: dict[str, Any] = {
        "strategy": strategy,
        "dispatched_count": len(tasks),
        "skipped_count": skipped,
        "tasks": tasks,
    }
    if fallback_from_local_llm:
        result["local_llm_fallback"] = True
        result["note"] = (
            "saved preference 'local_llm' but no server reachable; "
            "fell back to 'subagent'. Run lint_fix_setup_local_llm to fix."
        )
    return result


def _llm_reachable() -> bool:
    """Cheap reachability probe — does any candidate LLM server respond?"""
    try:
        import lint_fix_setup as _setup
    except ImportError:
        return False
    try:
        return bool(_setup.detect_servers())
    except Exception:                                       # noqa: BLE001
        return False


__all__ = ["dispatch", "DEFAULT_ENV_VARS"]
