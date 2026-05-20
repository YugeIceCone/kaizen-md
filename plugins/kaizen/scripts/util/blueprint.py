"""kaizen-blueprint — one-shot creator for a planning blueprint JSON.

Matches the schema at
`.kaizen/superpowers/templates/planning-blueprint/blueprint.schema.json`.

Usage:
    kaizen-blueprint create
        [--project SLUG] [--out FILE] [--summary S]
        [--plan T]... [--research T]... [--task-list T]...
        [--spec T]... [--decision T]... [--idea T]...
        [--note T]... [--audit T]... [--brainstorm T]...
        [--guide T]...                                       (alias of note)
        [--no-session-meta] [--no-auto-link] [--json]

Each --<kind> is repeatable. Items get sequential ids (01, 02, ...) in
argv order. Auto-link: first item is root; subsequent items get
parents=[01] and the root's children list is filled. Session_meta is
auto-derived from git + the most-recent Claude Code session JSONL when
discoverable — skip with --no-session-meta.

# consolidated-cli-parent: kaizen-blueprint
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Kinds we accept directly + how each maps to (schema_kind, extra_tags).
# `guide` is the only alias — schema has 9 kinds, CLI has 10 flags.
_KIND_FLAGS: list[tuple[str, str, list[str]]] = [
    # (flag-name, schema-kind, default-tags)
    ("plan",       "plan",       []),
    ("research",   "research",   []),
    ("task-list",  "task-list",  []),
    ("spec",       "spec",       []),
    ("decision",   "decision",   []),
    ("idea",       "idea",       []),
    ("note",       "note",       []),
    ("audit",      "audit",      []),
    ("brainstorm", "brainstorm", []),
    ("guide",      "note",       ["guide"]),
]


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return _dt.date.today().isoformat()


def _git(repo: Path, *args: str) -> str | None:
    """Run a `git` command in `repo`; return stripped stdout or None on error."""
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(repo),
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        return r.stdout.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def _derive_session_meta(repo: Path, project: str) -> dict:
    """Best-effort session_meta. Never raises — missing pieces left out.

    Picks up:
      - git branch + HEAD for `project`
      - newest Claude Code JSONL under ~/.claude/projects/<cwd-slug>/
      - latest handoff yaml under ~/.claude/handoff/<project>/ → parent_*
    """
    meta: dict = {
        "generated_at": _now_iso(),
        "author":       "agent",
        "producer_tool": "kaizen-blueprint",
    }

    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(repo, "rev-parse", "--short", "HEAD")
    if branch:
        meta["primary_branch"] = {project: branch}
    if head:
        meta["head_at_generation"] = {project: head}

    # Newest CC JSONL for this cwd (graceful no-op when unreachable)
    home = Path.home()
    slug = "-" + str(repo).replace("/", "-")
    projects_dir = home / ".claude" / "projects" / slug
    if projects_dir.is_dir():
        jsonls = sorted(projects_dir.glob("*.jsonl"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if jsonls:
            j = jsonls[0]
            meta["cc_session_jsonl"] = str(j)
            meta["cc_session_uuid"] = j.stem
            try:
                blob = j.read_bytes()
                meta["cc_session_sha256"] = hashlib.sha256(blob).hexdigest()
                meta["cc_session_size_bytes"] = len(blob)
                meta["cc_session_lines"] = sum(
                    1 for ln in blob.splitlines() if ln.strip())
            except OSError:
                pass

    # Newest handoff yaml under ~/.claude/handoff/<project>/
    handoff_dir = home / ".claude" / "handoff" / project
    if handoff_dir.is_dir():
        yamls = sorted(handoff_dir.glob("*.yaml"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
        if yamls:
            meta["parent_handoff"] = str(yamls[0])
            # Scrape parent session UUID from the yaml's session_meta block
            try:
                txt = yamls[0].read_text(encoding="utf-8")
                for line in txt.splitlines():
                    s = line.strip()
                    if s.startswith("cc_session_uuid:"):
                        val = s.split(":", 1)[1].strip().strip("'\"")
                        if val:
                            meta["parent_session_uuid"] = val
                        break
            except OSError:
                pass

    return meta


def _build_item(seq: int, kind: str, title: str,
                 extra_tags: list[str]) -> dict:
    today = _today()
    tags = list(extra_tags)
    return {
        "id":          f"{seq:02d}",
        "kind":        kind,
        "title":       title,
        "status":      "draft",
        "summary":     "",
        "created":     today,
        "updated":     today,
        "tags":        tags,
        "owner":       "agent",
        "links": {
            "parents": [], "children": [], "related": [],
            "supersedes": [], "superseded_by": None,
        },
        "content":     None,
        "content_ref": None,
        "tasks":       [] if kind == "task-list" else None,
        "outcome":     None,
        "outcome_justification": None,
        "confidence":  None,
        "sources":     [],
        "session_origin": None,
        "meta":        {},
    }


def _auto_link(items: list[dict]) -> None:
    """First item is root; subsequent items get parents=[root.id] and
    root.children is filled. Idempotent — skips when items already linked."""
    if len(items) < 2:
        return
    root = items[0]
    root_id = root["id"]
    child_ids: list[str] = []
    for item in items[1:]:
        if root_id not in item["links"]["parents"]:
            item["links"]["parents"].append(root_id)
        child_ids.append(item["id"])
    for cid in child_ids:
        if cid not in root["links"]["children"]:
            root["links"]["children"].append(cid)


def _collect_items_from_args(args: argparse.Namespace) -> list[dict]:
    """Walk argv-order across all --<kind> flag groups so item ids match
    the order the user typed them.

    argparse strips order across groups. We re-derive it by parsing argv
    once more — KISS, no custom Action class needed."""
    order: list[tuple[str, str]] = []  # (schema_kind, title)
    extra_tags_by_kind = {flag: tags for flag, _, tags in _KIND_FLAGS}
    schema_kind_by_flag = {flag: kind for flag, kind, _ in _KIND_FLAGS}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            flag_name = a[2:]
            if flag_name in schema_kind_by_flag:
                if i + 1 < len(argv):
                    title = argv[i + 1]
                    order.append((flag_name, title))
                    i += 2
                    continue
        i += 1

    items: list[dict] = []
    seq = 1
    for flag_name, title in order:
        items.append(_build_item(
            seq, schema_kind_by_flag[flag_name],
            title, extra_tags_by_kind[flag_name],
        ))
        seq += 1
    return items


def _cmd_create(args: argparse.Namespace) -> int:
    items = _collect_items_from_args(args)
    if not items:
        sys.stderr.write(
            "blueprint create: at least one --<kind> TITLE flag required "
            "(plan / research / task-list / spec / decision / idea / note / "
            "audit / brainstorm / guide)\n"
        )
        return 2

    if not args.no_auto_link:
        _auto_link(items)

    repo = Path.cwd().resolve()
    project = args.project
    if not project:
        root = _git(repo, "rev-parse", "--show-toplevel")
        project = Path(root).name if root else repo.name

    doc: dict = {
        "$schema": "https://kaizen-md/templates/planning-blueprint/blueprint.schema.json",
        "blueprint_version": "1",
        "project": project,
        "generated_at": _now_iso(),
    }
    if args.summary:
        doc["summary"] = args.summary
    if not args.no_session_meta:
        meta = _derive_session_meta(repo, project)
        if meta:
            doc["session_meta"] = meta
    doc["items"] = items

    body = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: tempfile-then-rename
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(out)
        if args.json:
            sys.stdout.write(json.dumps(
                {"file_path": str(out.resolve()), "item_count": len(items)},
                ensure_ascii=False,
            ) + "\n")
        else:
            sys.stdout.write(
                f"blueprint create: wrote {len(items)} item(s) → {out}\n")
    else:
        sys.stdout.write(body + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-blueprint",
        description="One-shot planning blueprint creator.",
    )
    sub = p.add_subparsers(dest="command")

    c = sub.add_parser("create", help="create a new blueprint JSON")
    c.add_argument("--project", default=None,
                    help="project slug (default: repo basename)")
    c.add_argument("--out", default=None,
                    help="output file (default: stdout)")
    c.add_argument("--summary", default=None)
    for flag_name, _, _ in _KIND_FLAGS:
        c.add_argument(f"--{flag_name}", action="append", default=[],
                        help=f"add a {flag_name!r} item (repeatable)")
    c.add_argument("--no-session-meta", action="store_true",
                    help="skip the session_meta block")
    c.add_argument("--no-auto-link", action="store_true",
                    help="don't auto-link subsequent items to the first as root")
    c.add_argument("--json", action="store_true",
                    help="emit machine summary on stdout (only meaningful with --out)")
    c.set_defaults(fn=_cmd_create)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
