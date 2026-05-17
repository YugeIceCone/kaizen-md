#!/usr/bin/env python3
"""kaizen-gold — incidental-discovery + learnings tracker.

Sits BETWEEN dxm (raw events) and brain (consolidated beliefs). Catches
the "ha!" moments that emerge mid-work — patterns, gotchas, hidden
contracts — before they decay. Later `promote` graduates the durable
ones to CLAUDE.md rules / brain Notes.

## Storage

  $KAIZEN_DIR/gold/<project-slug>/patterns.jsonl  (append-only)

Schema per line:
  {id, ts, tag, pattern, source?, learned?, promoted, promoted_to}

## Subcommands

  capture "<pattern>" [--tag X] [--source <path:line>] [--learned "<context>"]
  list [--tag X] [--unpromoted] [--limit N] [--json]
  show <id> [--json]
  promote <id> --to <target> [--note "<context>"]

`promote` atomic-appends a `- [gold #<id>] <pattern>` line to the
target file (CLAUDE.md, brain Note, etc.) and marks the entry promoted.
The append goes via _atomic.atomic_append_line.

## Use cases

- Bash quirks ("subprocess cwd persists across Bash tool calls")
- Hidden contracts ("skill-suggest only matches QUOTED phrases")
- Per-dir gotchas (".kaizen/.gitignore whitelist overrides repo-root")
- Model-aware surprises ("JSONL strips [1m] from model id")
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent


def _kaizen_dir() -> Path:
    env = os.environ.get("KAIZEN_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen"


def _project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".kaizen").is_dir() or (parent / ".git").is_dir():
            return parent
    return cwd


def _project_slug() -> str:
    return str(_project_root().resolve()).replace("/", "-")


def _patterns_path() -> Path:
    env = os.environ.get("KAIZEN_GOLD_FILE")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return _kaizen_dir() / "gold" / _project_slug() / "patterns.jsonl"


def _iso_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_id(path: Path) -> int:
    if not path.is_file():
        return 1
    max_id = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec.get("id"), int) and rec["id"] > max_id:
                    max_id = rec["id"]
    except OSError:
        return 1
    return max_id + 1


def _read_all(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def _atomic_append(path: Path, line: str) -> None:
    """Append via _atomic when available; stdlib fallback."""
    try:
        sys.path.insert(0, str(_SCRIPT_DIR))
        import _atomic
        _atomic.atomic_append_line(path, line)
    except (OSError, ImportError):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + ("" if line.endswith("\n") else "\n"))


def _emit_event(evt: str, data: dict) -> None:
    """Fire trace + dxm events for `evt` with `data`. Best-effort.

    DRY: capture + promote both want trace (durable, searchable) + dxm
    (live mirror). Both subsystems own their own writer; this function
    is the single fan-out. Honors KAIZEN_GOLD_DISABLE to suppress.
    """
    if os.environ.get("KAIZEN_GOLD_DISABLE") == "1":
        return
    sys.path.insert(0, str(_SCRIPT_DIR))
    try:
        import trace as _trace
        _trace.append_event({
            "ts":   _iso_now(),
            "src":  "tool",
            "evt":  evt,
            "tool": "kaizen-gold",
            "data": data,
        })
    except Exception:
        pass
    try:
        import _dxm_emit
        _dxm_emit.emit_event(evt, tool_name="kaizen-gold", payload=data)
    except Exception:
        pass


def _cmd_capture(args) -> int:
    p = _patterns_path()
    rec = {
        "id":           _next_id(p),
        "ts":           _iso_now(),
        "tag":          args.tag or "",
        "pattern":      args.pattern,
        "source":       args.source or "",
        "learned":      args.learned or "",
        "promoted":     False,
        "promoted_to":  "",
    }
    _atomic_append(p, json.dumps(rec))
    _emit_event("gold.captured", {
        "id":      rec["id"],
        "tag":     rec["tag"],
        "pattern": rec["pattern"],
    })
    if args.json:
        print(json.dumps(rec))
    else:
        print(f"[kaizen-gold] captured #{rec['id']} (tag={rec['tag'] or '-'})")
    return 0


def _cmd_list(args) -> int:
    p = _patterns_path()
    recs = _read_all(p)
    if args.tag:
        recs = [r for r in recs if r.get("tag") == args.tag]
    if args.unpromoted:
        recs = [r for r in recs if not r.get("promoted")]
    if args.limit and args.limit > 0:
        recs = recs[-args.limit:]
    if args.json:
        print(json.dumps(recs, indent=2))
    else:
        if not recs:
            print("[kaizen-gold] (no entries)")
            return 0
        for r in recs:
            mark = "✓" if r.get("promoted") else "·"
            tag = f"[{r['tag']}] " if r.get("tag") else ""
            print(f"  {mark} #{r['id']:<4d} {tag}{r['pattern']}")
            if r.get("source"):
                print(f"        src: {r['source']}")
    return 0


def _cmd_show(args) -> int:
    p = _patterns_path()
    for r in _read_all(p):
        if r.get("id") == args.id:
            print(json.dumps(r, indent=2) if args.json
                  else "\n".join(f"{k}: {v}" for k, v in r.items()))
            return 0
    sys.stderr.write(f"[kaizen-gold] no entry with id {args.id}\n")
    return 1


def _brain_note_body(rec: dict) -> str:
    """Build a brain-Note file body (frontmatter + h1 + provenance).

    Mirrors the shape under ~/.claude/.kaizen/brain/Notes/ — type=belief,
    confidence=0.5 (fresh promotion, not yet reinforced), tags carry
    'gold' + the entry's own tag. The pattern becomes the h1; source
    + learned context land as labeled lines beneath.
    """
    today = _dt.date.today().isoformat()
    tags = ["gold"]
    if rec.get("tag"):
        tags.append(rec["tag"])
    tags_yaml = "[" + ", ".join(tags) + "]"
    lines = [
        "---",
        f"created: {today}",
        f"updated: {today}",
        "type: belief",
        "confidence: 0.5",
        f"tags: {tags_yaml}",
        "sources_count: 1",
        "---",
        "",
        f"# {rec['pattern']}",
        "",
    ]
    if rec.get("source"):
        lines.append(f"**Source:** `{rec['source']}`")
    if rec.get("learned"):
        lines.append(f"**Learned:** {rec['learned']}")
    lines.append("")
    lines.append(f"_Promoted from gold #{rec['id']} ({rec['ts']})._")
    lines.append("")
    return "\n".join(lines)


def _cmd_promote(args) -> int:
    """Atomic-append the gold pattern to <target> and mark promoted.

    Default append shape: `- [gold #<id>] <pattern>` (with optional
    --note context). With `--brain`, when the target file does NOT
    yet exist, the file is created with a brain Note frontmatter
    block + h1 + provenance lines. Use --brain to graduate a pattern
    into ~/.claude/.kaizen/brain/Notes/.
    """
    p = _patterns_path()
    recs = _read_all(p)
    target = None
    for r in recs:
        if r.get("id") == args.id:
            target = r
            break
    if target is None:
        sys.stderr.write(f"[kaizen-gold] no entry with id {args.id}\n")
        return 1
    if target.get("promoted"):
        sys.stderr.write(f"[kaizen-gold] #{args.id} already promoted to "
                          f"{target.get('promoted_to')}\n")
        return 1

    dest = Path(args.to).expanduser()

    if args.brain and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            sys.path.insert(0, str(_SCRIPT_DIR))
            import _atomic
            _atomic.atomic_write(dest, _brain_note_body(target))
        except (OSError, ImportError):
            dest.write_text(_brain_note_body(target), encoding="utf-8")
    else:
        line = f"- [gold #{target['id']}] {target['pattern']}"
        if args.note:
            line += f"  ({args.note})"
        _atomic_append(dest, line)

    # Mark promoted by rewriting the JSONL (read-all + atomic_write)
    new_recs = []
    for r in recs:
        if r.get("id") == args.id:
            r["promoted"] = True
            r["promoted_to"] = str(dest)
            r["promoted_at"] = _iso_now()
        new_recs.append(r)
    try:
        sys.path.insert(0, str(_SCRIPT_DIR))
        import _atomic
        _atomic.atomic_write(p, "\n".join(json.dumps(r)
                                            for r in new_recs) + "\n")
    except (OSError, ImportError):
        p.write_text("\n".join(json.dumps(r) for r in new_recs) + "\n",
                      encoding="utf-8")

    _emit_event("gold.promoted", {
        "id":    args.id,
        "to":    str(dest),
        "brain": bool(args.brain),
    })
    if args.json:
        print(json.dumps({"promoted_id": args.id, "to": str(dest)}))
    else:
        print(f"[kaizen-gold] promoted #{args.id} → {dest}")
    return 0


def _cmd_path(args) -> int:
    print(_patterns_path())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-gold",
        description="Track incidental discoveries + learnings; promote durable ones.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("capture", help="capture a gold pattern")
    pc.add_argument("pattern", help="one-line pattern / learning / gotcha")
    pc.add_argument("--tag", default="", help="short tag for grouping")
    pc.add_argument("--source", default="",
                     help="optional source ref (path:line or skill name)")
    pc.add_argument("--learned", default="",
                     help="optional context: how we learned this")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=_cmd_capture)

    pl = sub.add_parser("list", help="list captured patterns")
    pl.add_argument("--tag", default=None)
    pl.add_argument("--unpromoted", action="store_true",
                     help="only entries not yet promoted")
    pl.add_argument("--limit", type=int, default=0)
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=_cmd_list)

    ps = sub.add_parser("show", help="show one entry by id")
    ps.add_argument("id", type=int)
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=_cmd_show)

    pp = sub.add_parser("promote",
                          help="atomic-append `- [gold #N] <pattern>` to a target file, mark promoted")
    pp.add_argument("id", type=int)
    pp.add_argument("--to", required=True,
                     help="target file (CLAUDE.md / brain Note / plan file)")
    pp.add_argument("--note", default="", help="optional context to append")
    pp.add_argument("--brain", action="store_true",
                     help="when --to is a non-existent path, create it as "
                          "a brain Note (frontmatter + h1 + provenance) "
                          "instead of appending a bare bullet")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=_cmd_promote)

    pth = sub.add_parser("path", help="print storage path")
    pth.set_defaults(func=_cmd_path)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
