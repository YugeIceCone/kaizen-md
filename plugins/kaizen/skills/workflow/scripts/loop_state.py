#!/usr/bin/env python3
"""Controlled CRUD helpers for the kaizen Ralph-loop state file.

Provides the AGENT-FACING surface to read and mutate `.kaizen/loop.state.md`
without trusting the agent to hand-edit the JSON body. Pairs with
`loop_ledger.py` (the hook-side transition helper).

## Why this exists

Direct JSON edits to `.kaizen/loop.state.md` are technically possible (any
text Edit tool can write the file) but invite cheating:
- adding forged entries to `completed`
- silently removing un-gated items from `pending`
- breaking the frontmatter / JSON schema

This module is the audited, validated alternative. Every mutation:
- Preserves the YAML frontmatter byte-for-byte
- Validates the body parses as JSON with the expected schema
- Records the operation in `completed` (for `complete_item`) with iteration
  + manual: true so the audit log shows agent vs hook authorship
- Auto-assigns stable IDs (`i1`, `i2`, ...) to items so later operations
  can reference them unambiguously

## Public API

    state_path()            -> resolve .kaizen/loop.state.md from cwd
    load(path)              -> (frontmatter_str, body_dict, iteration_int)
    save(path, fm, body)    -> rewrite the file atomically

    add_item(desc, verify=None, path=None) -> {id, desc, verify}
        Append a new pending item. Auto-IDs.

    list_pending(path=None) -> [{id, desc, verify}, ...]
    list_completed(path=None) -> [{id?, desc, verify, iteration, completed_at}, ...]

    complete_item(id_or_desc, path=None, note=None) -> {…removed_item}
        Mark a verify=null (trust-based) item as completed. Records
        manual=true in the completed entry. NOT for items with verify —
        those must pass the hook's verify gate (cheat-proof path).

    status(path=None) -> {iteration, max_iterations, pending_count,
                          completed_count, started_at}

## CLI

    python3 loop_state.py add "desc" [--verify "cmd"]
    python3 loop_state.py list [--pending|--completed|--all]
    python3 loop_state.py status [--json]
    python3 loop_state.py complete <id-or-desc> [--note "..."]
    python3 loop_state.py cancel    # equivalent of /kaizen:loop --cancel

Exit codes: 0 = success, 1 = no loop active, 2 = bad arguments / schema
mismatch.

## Cross-CLI

Works from any host. State file resolution honors `KAIZEN_LOOP_STATE` env
var, else `<cwd>/.kaizen/loop.state.md`. The MCP wrapper `loop_mcp.py`
spawns from the project directory so cwd resolution works out of the box.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path


def state_path(cwd: Path | None = None) -> Path:
    """Resolve the loop state file: env override → <cwd>/.kaizen/loop.state.md."""
    env = os.environ.get("KAIZEN_LOOP_STATE")
    if env:
        return Path(env).expanduser().resolve()
    base = cwd or Path.cwd()
    return base / ".kaizen" / "loop.state.md"


def _split(text: str) -> tuple[str, str]:
    """Return (frontmatter_block_with_delimiters, body)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return "", text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return "", text
    fm = "\n".join(lines[: end_idx + 1])
    body = "\n".join(lines[end_idx + 1 :])
    return fm, body


def _iteration(fm: str) -> int:
    """Pull `iteration: N` from frontmatter; 0 if unparseable."""
    for line in fm.split("\n"):
        if line.strip().startswith("iteration:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                return 0
    return 0


def _ensure_ledger(body: str) -> dict:
    """Parse body as ledger dict; convert freeform legacy body if needed."""
    stripped = body.strip()
    if not stripped:
        return {"pending": [], "completed": []}
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if not isinstance(data, dict):
                raise ValueError("body is not a JSON object")
            data.setdefault("pending", [])
            data.setdefault("completed", [])
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"body is not valid JSON: {e}") from e
    # Legacy freeform body — wrap as a single trust-based item.
    return {
        "pending": [{"id": "i1", "desc": stripped, "verify": None}],
        "completed": [],
    }


def load(path: Path | None = None) -> tuple[str, dict, int]:
    """Load (frontmatter_str, ledger_dict, iteration_int) from the state file."""
    p = path or state_path()
    if not p.is_file():
        raise FileNotFoundError(f"no loop state file at {p}")
    text = p.read_text()
    fm, body = _split(text)
    ledger = _ensure_ledger(body)
    return fm, ledger, _iteration(fm)


def save(path: Path | None, fm: str, ledger: dict) -> None:
    """Rewrite the state file: preserve frontmatter, re-serialize JSON body."""
    p = path or state_path()
    body_json = json.dumps(ledger, indent=2)
    p.write_text(f"{fm}\n{body_json}\n")


def _next_id(pending: list[dict], completed: list[dict]) -> str:
    """Find the next free `i<N>` ID. Scans both lists for max existing N."""
    max_n = 0
    for it in list(pending) + list(completed):
        if not isinstance(it, dict):
            continue
        raw = it.get("id") or ""
        if raw.startswith("i"):
            try:
                max_n = max(max_n, int(raw[1:]))
            except ValueError:
                pass
    return f"i{max_n + 1}"


def add_item(
    desc: str,
    verify: str | None = None,
    path: Path | None = None,
) -> dict:
    """Append a new pending item with an auto-assigned ID. Returns the item."""
    if not desc or not desc.strip():
        raise ValueError("desc is required and cannot be empty")
    fm, ledger, _ = load(path)
    new_id = _next_id(ledger["pending"], ledger["completed"])
    item = {"id": new_id, "desc": desc.strip()}
    if verify is not None and verify.strip():
        item["verify"] = verify.strip()
    else:
        item["verify"] = None
    ledger["pending"].append(item)
    save(path, fm, ledger)
    return item


def list_pending(path: Path | None = None) -> list[dict]:
    _, ledger, _ = load(path)
    return list(ledger.get("pending") or [])


def list_completed(path: Path | None = None) -> list[dict]:
    _, ledger, _ = load(path)
    return list(ledger.get("completed") or [])


def status(path: Path | None = None) -> dict:
    p = path or state_path()
    if not p.is_file():
        return {"active": False, "state_path": str(p)}
    fm, ledger, iteration = load(p)
    # Extract started_at + max_iterations from frontmatter for the summary
    started_at, max_iterations, completion_promise = "", "0", "null"
    for line in fm.split("\n"):
        s = line.strip()
        if s.startswith("started_at:"):
            started_at = s.split(":", 1)[1].strip().strip('"')
        elif s.startswith("max_iterations:"):
            max_iterations = s.split(":", 1)[1].strip()
        elif s.startswith("completion_promise:"):
            completion_promise = s.split(":", 1)[1].strip()
    return {
        "active": True,
        "state_path": str(p),
        "iteration": iteration,
        "max_iterations": int(max_iterations) if max_iterations.isdigit() else 0,
        "completion_promise": completion_promise,
        "started_at": started_at,
        "pending_count": len(ledger["pending"]),
        "completed_count": len(ledger["completed"]),
    }


def _find_item(items: list[dict], id_or_desc: str) -> tuple[int, dict] | None:
    """Find a pending item by ID match (exact) or desc substring match."""
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        if it.get("id") == id_or_desc:
            return i, it
    # Fallback: desc substring match (case-insensitive)
    lower = id_or_desc.lower()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        desc = (it.get("desc") or "").lower()
        if lower in desc:
            return i, it
    return None


def complete_item(
    id_or_desc: str,
    path: Path | None = None,
    note: str | None = None,
) -> dict:
    """Move a pending item to completed (manual: true).

    Refuses items that have a `verify` command — those must pass the
    hook's verify gate. Use this only for `verify: null` trust-based items.

    Returns the completed entry."""
    fm, ledger, iteration = load(path)
    found = _find_item(ledger["pending"], id_or_desc)
    if not found:
        raise KeyError(f"no pending item matching {id_or_desc!r}")
    idx, item = found
    if item.get("verify"):
        raise ValueError(
            f"item {item.get('id')!r} has a verify command — let the hook "
            "gate it (do not manually complete verify-bearing items)"
        )
    entry = {
        **item,
        "iteration": iteration,
        "completed_at": dt.datetime.now(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "manual": True,
    }
    if note:
        entry["note"] = note
    del ledger["pending"][idx]
    ledger["completed"].append(entry)
    save(path, fm, ledger)
    return entry


def emit_promise(phrase: str, path: Path | None = None) -> dict:
    """Structured completion signal — writes `phrase` to a `last_promise`
    field in the state file's frontmatter. The Stop hook checks this
    field BEFORE the regex-based promise extraction, so a tool call here
    is unambiguous (cannot be confused with text content like a code-
    fence example).

    The phrase MUST exactly match the loop's configured `completion_promise`
    or this is a no-op (the Stop hook will not end the loop on a mismatch).

    Returns {emitted, matches, phrase} where `matches` is True iff the
    phrase matched the configured completion_promise."""
    if not phrase or not phrase.strip():
        raise ValueError("phrase is required and cannot be empty")
    p = path or state_path()
    if not p.is_file():
        raise FileNotFoundError(f"no loop state file at {p}")
    text = p.read_text()
    fm, body = _split(text)
    # Parse frontmatter to read the configured promise
    configured = ""
    for line in fm.split("\n"):
        s = line.strip()
        if s.startswith("completion_promise:"):
            configured = s.split(":", 1)[1].strip().strip('"')
            if configured.lower() == "null":
                configured = ""
            break
    # Inject (or replace) `last_promise:` line BEFORE the closing `---`.
    new_fm_lines: list[str] = []
    inserted = False
    for line in fm.split("\n"):
        s = line.strip()
        if s.startswith("last_promise:"):
            new_fm_lines.append(f'last_promise: "{phrase.strip()}"')
            inserted = True
        elif s == "---" and not inserted and len(new_fm_lines) > 1:
            new_fm_lines.append(f'last_promise: "{phrase.strip()}"')
            new_fm_lines.append(line)
            inserted = True
        else:
            new_fm_lines.append(line)
    new_fm = "\n".join(new_fm_lines)
    p.write_text(f"{new_fm}\n{body}".rstrip() + "\n")
    return {
        "emitted": True,
        "phrase": phrase.strip(),
        "matches": phrase.strip() == configured.strip(),
        "configured_promise": configured,
    }


def cancel(path: Path | None = None) -> dict:
    """Remove the state file (equivalent of /kaizen:loop --cancel)."""
    p = path or state_path()
    if not p.is_file():
        return {"cancelled": False, "reason": "no loop active"}
    try:
        fm, ledger, iteration = load(p)
    except (FileNotFoundError, ValueError):
        ledger = {"pending": [], "completed": []}
        iteration = 0
    p.unlink()
    return {
        "cancelled": True,
        "iteration": iteration,
        "pending_count": len(ledger.get("pending") or []),
        "completed_count": len(ledger.get("completed") or []),
    }


# ─── CLI ─────────────────────────────────────────────────────────────


def _print_items(items: list[dict], kind: str) -> None:
    if not items:
        print(f"(no {kind} items)")
        return
    for it in items:
        ident = it.get("id") or "?"
        desc = it.get("desc") or "(no description)"
        verify = it.get("verify")
        suffix = f"  verify: {verify}" if verify else "  (no verify)"
        line = f"  [{ident}] {desc}{suffix}"
        if "iteration" in it:
            line += f"  (iter {it['iteration']}"
            if it.get("manual"):
                line += ", manual"
            line += ")"
        print(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kaizen-loop",
        description="Controlled access to the kaizen Ralph-loop state file.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="append a new pending item")
    pa.add_argument("desc")
    pa.add_argument("--verify", help="bash command run by the hook's verify gate")
    pa.add_argument("--json", action="store_true")

    pl = sub.add_parser("list", help="show ledger contents")
    grp = pl.add_mutually_exclusive_group()
    grp.add_argument("--pending", action="store_true", default=True)
    grp.add_argument("--completed", action="store_true")
    grp.add_argument("--all", action="store_true")
    pl.add_argument("--json", action="store_true")

    ps = sub.add_parser("status", help="loop iteration + counts")
    ps.add_argument("--json", action="store_true")

    pc = sub.add_parser("complete", help="manually complete a verify=null item")
    pc.add_argument("id_or_desc")
    pc.add_argument("--note")
    pc.add_argument("--json", action="store_true")

    pp = sub.add_parser(
        "promise",
        help="emit the completion promise via structured tool call "
             "(unambiguous — cannot be confused with text mentions)",
    )
    pp.add_argument("phrase", help="must match the loop's configured completion_promise")
    pp.add_argument("--json", action="store_true")

    px = sub.add_parser("cancel", help="remove the state file (end the loop)")
    px.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "add":
            item = add_item(args.desc, verify=args.verify)
            if args.json:
                print(json.dumps(item, indent=2))
            else:
                v = f" (verify: {item['verify']})" if item.get("verify") else ""
                print(f"added: [{item['id']}] {item['desc']}{v}")
            return 0
        if args.cmd == "list":
            if args.all:
                pending = list_pending()
                completed = list_completed()
                if args.json:
                    print(json.dumps({"pending": pending, "completed": completed}, indent=2))
                else:
                    print("pending:")
                    _print_items(pending, "pending")
                    print("completed:")
                    _print_items(completed, "completed")
                return 0
            if args.completed:
                items = list_completed()
                kind = "completed"
            else:
                items = list_pending()
                kind = "pending"
            if args.json:
                print(json.dumps(items, indent=2))
            else:
                _print_items(items, kind)
            return 0
        if args.cmd == "status":
            s = status()
            if args.json:
                print(json.dumps(s, indent=2))
            else:
                if not s["active"]:
                    print(f"no active loop ({s['state_path']})")
                    return 1
                print(f"iteration:      {s['iteration']} / {s['max_iterations'] or 'unlimited'}")
                print(f"pending:        {s['pending_count']}")
                print(f"completed:      {s['completed_count']}")
                print(f"started:        {s['started_at']}")
                print(f"promise:        {s['completion_promise']}")
                print(f"state:          {s['state_path']}")
            return 0
        if args.cmd == "complete":
            entry = complete_item(args.id_or_desc, note=args.note)
            if args.json:
                print(json.dumps(entry, indent=2))
            else:
                print(f"completed: [{entry.get('id', '?')}] {entry['desc']}")
            return 0
        if args.cmd == "promise":
            result = emit_promise(args.phrase)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                if result["matches"]:
                    print(f"promise emitted: {result['phrase']!r} "
                          f"(matches configured — loop will end on next Stop)")
                else:
                    print(f"promise emitted: {result['phrase']!r} "
                          f"(does NOT match configured {result['configured_promise']!r})")
                    return 1
            return 0
        if args.cmd == "cancel":
            result = cancel()
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                if result["cancelled"]:
                    print(
                        f"cancelled loop at iteration {result['iteration']} "
                        f"({result['pending_count']} pending, "
                        f"{result['completed_count']} completed)"
                    )
                else:
                    print(result["reason"])
                    return 1
            return 0
    except FileNotFoundError as e:
        sys.stderr.write(f"kaizen-loop: {e}\n")
        return 1
    except (KeyError, ValueError) as e:
        sys.stderr.write(f"kaizen-loop: {e}\n")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
