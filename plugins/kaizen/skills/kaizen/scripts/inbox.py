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
    override = os.environ.get("KAIZEN_INBOX_DIR")
    if override:
        return Path(override)
    return Path(os.path.expanduser("~/.claude/kaizen-inbox"))


def _ensure() -> Path:
    d = inbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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
    lines = ["USER MESSAGE(S) RECEIVED WHILE BUSY:"]
    now_iso = _ts_iso()
    for m in pending:
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
    lines.append("(Pause current task to acknowledge these if relevant.)")
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


if __name__ == "__main__":
    main()
