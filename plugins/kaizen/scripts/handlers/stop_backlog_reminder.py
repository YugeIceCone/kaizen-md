"""kaizen stop_backlog_reminder — consolidated Stop-hook backlog check.

Reads backlog.json once, counts in_flight items, emits the final
hook JSON (either {} no-op, a soft systemMessage, or a hard-block
decision when KAIZEN_STOP_BLOCK_INFLIGHT=1).

Replaces 3 python3 spawns in stop-backlog-reminder.sh:
  1. count in_flight from backlog.json
  2. extract titles from backlog.json (redundant re-open!)
  3. format the final JSON payload

Bypass: this script returns {} when no .kaizen.toml or no
backlog.json exists. The host hook may be no-op'd entirely
with KAIZEN_BACKLOG_DISABLE=1 (checked here for parity with
other hooks' bypass convention).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


_EMPTY = "{}"


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
    """Read backlog_path from .kaizen.toml. Returns absolute path
    to backlog.json (alongside the backlog.md), or None."""
    toml = repo / ".kaizen.toml"
    if not toml.is_file():
        return None
    try:
        text = toml.read_text(encoding="utf-8")
    except OSError:
        return None
    # Match: backlog_path = "..."
    m = re.search(r'^\s*backlog_path\s*=\s*"?([^"\n]+)"?', text, re.MULTILINE)
    if not m:
        return None
    md_path = m.group(1).strip()
    if not md_path:
        return None
    # backlog.json sits alongside backlog.md
    json_rel = md_path[:-3] + ".json" if md_path.endswith(".md") else md_path + ".json"
    return repo / json_rel


def _scan_in_flight(backlog_json: Path) -> tuple[int, list[tuple[str, str]]]:
    """Returns (count, [(id, title), ...]) for items in in_flight section."""
    try:
        data = json.loads(backlog_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, []
    items = data.get("items", [])
    in_flight = [(it.get("id", "?"), it.get("title", "?"))
                  for it in items
                  if isinstance(it, dict) and it.get("section") == "in_flight"]
    return len(in_flight), in_flight


def _format_titles(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"  - {bk_id}: {title}" for bk_id, title in items)


def main() -> int:
    if os.environ.get("KAIZEN_BACKLOG_DISABLE") == "1":
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

    count, items = _scan_in_flight(backlog_json)
    if count == 0:
        print(_EMPTY)
        return 0

    titles = _format_titles(items)
    hard_block = os.environ.get("KAIZEN_STOP_BLOCK_INFLIGHT") == "1"

    if hard_block:
        reason = (f"{count} in_flight backlog item(s) remain:\n{titles}\n"
                   "Tick them via kaizen-backlog tick BK-N --committed <sha>, "
                   "or move back to next_up if not actually started.")
        print(json.dumps({"decision": "block", "reason": reason}))
    else:
        msg = (f"⚠ kaizen: {count} in_flight backlog item(s) pending:\n{titles}\n"
                "(set KAIZEN_STOP_BLOCK_INFLIGHT=1 to make this a hard block)")
        print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
