"""kaizen posttooluse_bash_commit — when Claude runs `git commit`,
suggest ticking backlog items mentioned in the commit message.

Replaces 4 python3 spawns in posttooluse-bash-commit.sh:
  1. extract cmd + rtype + content from event JSON
  2. count/match in_flight items vs commit message
  3. format final hook JSON
  (plus shell-side grep+sed for backlog_path)

Fires after every Bash, so a fast early-exit (not git commit / no
.kaizen.toml / no in_flight items) keeps the common case cheap.

Bypass: KAIZEN_BACKLOG_COMMIT_DISABLE=1.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_EMPTY = "{}"
_GIT_COMMIT_RE = re.compile(r"(^|[^a-zA-Z])git\s+commit")

def _resolve_repo() -> Path | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None

def _backlog_path(repo: Path) -> Path | None:
    toml = repo / ".kaizen.toml"
    if not toml.is_file():
        return None
    try:
        text = toml.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^\s*backlog_path\s*=\s*"?([^"\n]+)"?', text, re.MULTILINE)
    if not m:
        return None
    md_path = m.group(1).strip()
    if not md_path:
        return None
    json_rel = md_path[:-3] + ".json" if md_path.endswith(".md") else md_path + ".json"
    return repo / json_rel

def _latest_commit_msg(repo: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True, text=True, timeout=3,
        )
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""

def _match_in_flight_items(commit: str, items: list[dict]) -> list[tuple[str, str, str]]:
    """Returns [(id, title, kind), ...] where kind is 'id' or 'title'."""
    matches = []
    for it in items:
        if not isinstance(it, dict) or it.get("section") != "in_flight":
            continue
        item_id = it.get("id") or ""
        title = it.get("title") or ""
        if not item_id:
            continue
        # Strong signal: id explicitly mentioned
        if re.search(rf'\b{re.escape(item_id)}\b', commit):
            matches.append((item_id, title, "id"))
            continue
        # Weaker signal: first 4+ words of title appear (≥16 chars)
        title_words = title.split()[:4]
        title_frag = " ".join(title_words)
        if len(title_frag) >= 16 and title_frag.lower() in commit.lower():
            matches.append((item_id, title, "title"))
    return matches

def main() -> int:
    if os.environ.get("KAIZEN_BACKLOG_COMMIT_DISABLE") == "1":
        print(_EMPTY)
        return 0

    try:
        event = json.load(sys.stdin)
    except Exception:
        print(_EMPTY)
        return 0

    tool_input = event.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not _GIT_COMMIT_RE.search(cmd):
        print(_EMPTY)
        return 0

    # Tool errored → no suggestion
    tool_result = event.get("tool_result") or {}
    if isinstance(tool_result, dict) and tool_result.get("type") == "error":
        print(_EMPTY)
        return 0

    repo = _resolve_repo()
    if repo is None:
        print(_EMPTY)
        return 0

    backlog_json = _backlog_path(repo)
    if backlog_json is None or not backlog_json.is_file():
        print(_EMPTY)
        return 0

    commit = _latest_commit_msg(repo)
    if not commit.strip():
        print(_EMPTY)
        return 0

    try:
        data = json.loads(backlog_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(_EMPTY)
        return 0

    matches = _match_in_flight_items(commit, data.get("items", []))
    if not matches:
        print(_EMPTY)
        return 0

    lines = ["⚙ kaizen: commit landed; in_flight backlog item(s) likely tied:"]
    for mid, title, kind in matches:
        lines.append(f"  - {mid} ({kind}-match): {title}")
    lines.append("  Tick: kaizen-backlog tick <id> --committed <short-sha>")
    suggestion = "\n".join(lines)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": suggestion,
        }
    }))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
