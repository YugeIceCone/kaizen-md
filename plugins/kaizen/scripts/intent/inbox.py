#!/usr/bin/env python3
"""kaizen inbox — capture user messages, drain on next safe break.

Solves the "Claude is busy" gap: when the harness is mid-tool-call and
the user types a follow-up, that message normally only reaches Claude
at the END of the current tool sequence. The inbox captures every
UserPromptSubmit event into a small JSON file, and the PostToolUse
hook drains pending messages back into Claude's context as
additionalContext — so Claude sees user input on the very next tool
boundary, not after the whole sequence completes.

Location: `$HOME/.claude/kaizen-inbox/` (global, session-tagged).
Override with `KAIZEN_INBOX_DIR`.

Per-message file `<UTC>-<seq>.json`:

    {
      "ts": "2026-05-11T22:50:12.123Z",
      "session_id": "<cc session uuid or empty>",
      "prompt": "<verbatim user text>",
      "drained": false,
      "drained_at": null
    }

`capture` writes a new pending message. `drain` returns all currently
pending messages as a single formatted block AND flips `drained: true`
(so they don't re-surface). `list` is read-only. `clear` removes ALL
(pending + drained) — use for hygiene.

## CLI

    inbox.py capture <prompt> [--session SID]
    inbox.py list [--all]      → default = pending only
    inbox.py drain             → prints + marks drained
    inbox.py peek              → prints pending WITHOUT marking drained
    inbox.py clear             → removes all entries
    inbox.py stats             → counts
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

def inbox_dir() -> Path:
    # v1.22.0+: default location moved to ~/.claude/.kaizen/inbox/.
    # KAIZEN_INBOX_DIR still wins if set.
    override = os.environ.get("KAIZEN_INBOX_DIR")
    if override:
        return Path(override)
    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here))
    sys.path.insert(0, str(_here.parent / "io"))
    import _paths as _p  # noqa: E402
    return _p.INBOX_DIR

def _ensure() -> Path:
    d = inbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d

# scripts/intent/ → scripts/io/ for _time
_INBOX_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_INBOX_SCRIPT_DIR.parent / "io"))
from _time import utc_now  # M5 dedup

def _now() -> dt.datetime:
    return utc_now()

def _ts_iso() -> str:
    return _now().isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _ts_filename() -> str:
    return _now().strftime("%Y%m%dT%H%M%SZ")

# ─── Core ops ────────────────────────────────────────────────────────

def capture(prompt: str, session_id: str = "") -> Path:
    d = _ensure()
    stem = _ts_filename()
    n = 0
    while True:
        path = d / f"{stem}-{n:03d}.json"
        if not path.exists():
            break
        n += 1
    path.write_text(json.dumps({
        "ts": _ts_iso(),
        "session_id": session_id,
        "prompt": prompt,
        "drained": False,
        "drained_at": None,
    }, indent=2))
    return path

_SENTINEL_NAME = ".current-turn"

def _sentinel_path() -> Path:
    return inbox_dir() / _SENTINEL_NAME

def _turn_starter_file() -> str:
    """Return the absolute path string of the current turn's starter message,
    or "" if no sentinel exists. The sentinel is set by UserPromptSubmit hook
    on the first prompt of a turn and cleared by the Stop hook at turn end.
    Drain skips this file so the agent's own in-flight prompt doesn't
    re-surface as a 'while you were busy' message."""
    p = _sentinel_path()
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text())
        return data.get("path", "")
    except (OSError, json.JSONDecodeError):
        return ""

def set_turn_starter(captured_path: str) -> bool:
    """Write the sentinel ONLY if absent. Returns True if newly set,
    False if a sentinel already exists (this is a mid-turn message).
    Called by the UserPromptSubmit hook right after capture."""
    sentinel = _sentinel_path()
    if sentinel.exists():
        return False
    try:
        sentinel.write_text(json.dumps({
            "path": captured_path,
            "ts": _ts_iso(),
        }, indent=2))
        return True
    except OSError:
        return False

def clear_turn_starter() -> bool:
    """Remove the sentinel AND mark the starter message as drained.
    Called by the Stop hook at turn end. Both steps matter: clearing
    only the sentinel would leave the starter as a pending message
    that next-turn's drain would surface as 'while you were busy' —
    wrong, since it was the *previous* turn's starter, not a
    mid-busy interrupt."""
    sentinel = _sentinel_path()
    if not sentinel.exists():
        return False
    starter_path = ""
    try:
        data = json.loads(sentinel.read_text())
        starter_path = data.get("path", "")
    except (OSError, json.JSONDecodeError):
        pass

    # Mark starter as drained (it was processed during the turn)
    if starter_path:
        p = Path(starter_path)
        if p.exists():
            try:
                m = json.loads(p.read_text())
                m["drained"] = True
                m["drained_at"] = _ts_iso()
                m["drain_reason"] = "turn-starter-completed"
                p.write_text(json.dumps(m, indent=2))
            except (OSError, json.JSONDecodeError):
                pass

    try:
        sentinel.unlink()
        return True
    except OSError:
        return False

def list_messages(pending_only: bool = True) -> list[dict]:
    d = inbox_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for f in sorted(d.glob("*.json")):
        try:
            m = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if pending_only and m.get("drained"):
            continue
        m["_path"] = str(f)
        out.append(m)
    return out

def drain() -> str:
    pending = list_messages(pending_only=True)
    if not pending:
        return ""
    starter = _turn_starter_file()
    lines = ["USER MESSAGE(S) RECEIVED WHILE BUSY:"]
    now_iso = _ts_iso()
    for m in pending:
        if starter and m.get("_path") == starter:
            # Skip the prompt that started THIS turn — the agent is
            # already processing it; surfacing it would create the
            # "I already addressed this" echo bug.
            continue
        prompt = (m.get("prompt") or "").strip()
        if not prompt:
            continue
        lines.append(f"  [{m.get('ts', '?')}] {prompt}")
        # Mark drained
        try:
            payload = {k: v for k, v in m.items() if not k.startswith("_")}
            payload["drained"] = True
            payload["drained_at"] = now_iso
            Path(m["_path"]).write_text(json.dumps(payload, indent=2))
        except OSError:
            pass
    if len(lines) == 1:  # nothing real to surface
        return ""
    # The drain block is attached as a system-reminder to the current
    # tool result and PERSISTS in conversation context across later
    # turns. Once acknowledged, the reminder text doesn't disappear —
    # so the agent must not re-acknowledge on every subsequent turn.
    # See [[feedback-no-redundant-while-busy-ack]].
    lines.append(
        "(If your immediately prior assistant turn already addressed "
        "these, continue silently — do NOT re-acknowledge. Otherwise "
        "pause the current task to address them.)"
    )
    return "\n".join(lines)

def peek() -> str:
    pending = list_messages(pending_only=True)
    if not pending:
        return ""
    lines = []
    for m in pending:
        prompt = (m.get("prompt") or "").strip()
        if not prompt:
            continue
        lines.append(f"  [{m.get('ts', '?')}] {prompt}")
    return "\n".join(lines)

def clear() -> int:
    d = inbox_dir()
    if not d.exists():
        return 0
    n = 0
    for f in d.glob("*.json"):
        f.unlink()
        n += 1
    return n

def stats() -> dict:
    d = inbox_dir()
    if not d.exists():
        return {"dir": str(d), "exists": False, "pending": 0, "drained": 0, "total": 0}
    pending = drained_count = 0
    for f in d.glob("*.json"):
        try:
            m = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("drained"):
            drained_count += 1
        else:
            pending += 1
    return {
        "dir": str(d),
        "exists": True,
        "pending": pending,
        "drained": drained_count,
        "total": pending + drained_count,
    }

# ─── CLI ─────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(prog="inbox.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="save a new pending message")
    cap.add_argument("prompt")
    cap.add_argument("--session", default="")

    ls = sub.add_parser("list", help="list pending (default) or all")
    ls.add_argument("--all", action="store_true")

    sub.add_parser("drain", help="print pending + mark drained")
    sub.add_parser("peek", help="print pending without marking")
    sub.add_parser("clear", help="remove ALL entries")
    sub.add_parser("stats", help="print counts")
    ts = sub.add_parser("set-turn-starter",
                         help="write sentinel only if absent (UserPromptSubmit hook)")
    ts.add_argument("path", help="absolute path of the captured message")
    sub.add_parser("clear-turn-starter",
                   help="remove sentinel (Stop hook)")

    args = p.parse_args()

    if args.cmd == "capture":
        if not args.prompt.strip():
            sys.exit(0)  # ignore empties — no error
        path = capture(args.prompt, args.session)
        print(str(path))

    elif args.cmd == "list":
        msgs = list_messages(pending_only=not args.all)
        if not msgs:
            print("(empty)")
            return
        for m in msgs:
            tag = "drained" if m.get("drained") else "pending"
            ts = m.get("ts", "?")
            prompt = (m.get("prompt") or "")[:80].replace("\n", " ")
            print(f"  [{tag:7}] {ts}  {prompt}")

    elif args.cmd == "drain":
        out = drain()
        if out:
            print(out)

    elif args.cmd == "peek":
        out = peek()
        if out:
            print(out)

    elif args.cmd == "clear":
        n = clear()
        print(f"cleared {n} entries")

    elif args.cmd == "stats":
        print(json.dumps(stats(), indent=2))

    elif args.cmd == "set-turn-starter":
        ok = set_turn_starter(args.path)
        print("set" if ok else "already-set")

    elif args.cmd == "clear-turn-starter":
        ok = clear_turn_starter()
        print("cleared" if ok else "absent")

if __name__ == "__main__":
    main()
