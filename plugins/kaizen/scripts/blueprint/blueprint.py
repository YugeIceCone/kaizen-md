#!/usr/bin/env python3
"""kaizen-blueprint — 1-roundtrip plan management CLI.

Every subcommand reads / mutates / writes a blueprint.json in ONE
invocation. Mutating verbs route through _atomic.atomic_write_json so
partial writes are impossible.

## Subcommands

  show [file] [N]                      Print items[N] by array index.
  show [file] --id ID                  Print items[?].id == ID.
  show [file] --id ID --subtree[=H]    ID + linked children (H hops, default 1).
  show [file]                          Print whole plan (JSON).
  show [file] --md                     Render whole plan as markdown.

  list [file]                          One row per item — index / id / kind /
                                       status / title. Uses cache when fresh
                                       (1-roundtrip, no source read).

  scan                                 Pull cached rollup of the ACTIVE plan
                                       without touching source. Pure cache
                                       hit. Use to pick an index before
                                       fetching the full item.

  state [--json] [--clear [file]]      Inspect / clear the cache.

  validate <file>                      Schema + DAG check; exit 0/1.

  set-status [file] --id X --status S       Atomic item-status flip.
  set-task-status [file] --task-id X --status S   Atomic task-status flip.

  init <file> --topic T [--project P]  Create from template + fill placeholders.

## Active plan + 1-roundtrip semantics

Every read subcommand (show / list / scan) auto-caches metadata of the
named plan and marks it ACTIVE. Subsequent calls can omit the file
argument — they target the active plan. Common flows:

  # First time on a plan: cache populates, returns metadata (1 call)
  kaizen-blueprint list .kaizen/docs/plans/foo.json

  # Now subsequent reads are 1-roundtrip with no path:
  kaizen-blueprint scan                       # cache only, no source read
  kaizen-blueprint show 5                     # items[5] from active plan
  kaizen-blueprint show --id 04               # by id from active plan
  kaizen-blueprint set-status --id 04 --status shipped

Cache is mtime+size invalidated — touching the source file forces a
rebuild on next access. Override location via KAIZEN_BLUEPRINT_STATE.

## Why a CLI

Hand-editing JSON loses on:
  - Atomicity (cat | jq > tmp; mv tmp file — not atomic on crash)
  - Validation (no schema check unless you remember to run jsonschema)
  - DAG (broken links land silently)
  - Roundtrips (read + parse + edit + format + validate + write = 5+ calls)

This CLI collapses each to 1 call.

Stdlib + jsonschema (only on --validate).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent))
import _blueprint as bp  # noqa: E402
import _state as st  # noqa: E402


# ─── render helpers ─────────────────────────────────────────────────────

def _render_md(plan: dict) -> str:
    """Render the whole plan as a scannable markdown doc."""
    lines: list[str] = []
    lines.append(f"# {plan.get('project', '<unknown>')} — blueprint")
    lines.append("")
    if plan.get("summary"):
        lines.append(f"> {plan['summary']}")
        lines.append("")
    items = plan.get("items", [])
    lines.append(f"## Items ({len(items)})")
    lines.append("")
    lines.append("| # | id | kind | status | title |")
    lines.append("|---|---|---|---|---|")
    for i, it in enumerate(items):
        lines.append(
            f"| {i} | `{it.get('id', '')}` | {it.get('kind', '')} | "
            f"{it.get('status', '')} | {it.get('title', '')[:80]} |"
        )
    return "\n".join(lines) + "\n"


def _render_item_md(item: dict) -> str:
    """Render one item as markdown (compact)."""
    lines: list[str] = []
    lines.append(f"# {item.get('id')} — {item.get('title', '')}")
    lines.append("")
    lines.append(f"- **kind:** {item.get('kind')}")
    lines.append(f"- **status:** {item.get('status')}")
    if item.get("owner"):
        lines.append(f"- **owner:** {item['owner']}")
    if item.get("confidence") is not None:
        lines.append(f"- **confidence:** {item['confidence']}")
    if item.get("outcome"):
        lines.append(f"- **outcome:** {item['outcome']}")
    links = item.get("links", {})
    if any(links.values()):
        lines.append("- **links:**")
        for k, v in links.items():
            if v:
                lines.append(f"  - {k}: {v}")
    if item.get("summary"):
        lines.append("")
        lines.append(f"> {item['summary']}")
    if item.get("content"):
        lines.append("")
        lines.append(item["content"])
    if item.get("tasks"):
        lines.append("")
        lines.append("## Tasks")
        for t in item["tasks"]:
            mark = {"completed": "x", "in_progress": "-",
                    "pending": " ", "blocked": "!", "skipped": "~"}.get(
                t.get("status", ""), "?")
            lines.append(f"- [{mark}] **{t.get('id')}** — {t.get('subject', '')}")
    return "\n".join(lines) + "\n"


# ─── helpers ────────────────────────────────────────────────────────────

def _auto_discover_plan() -> str | None:
    """Walk .kaizen/docs/ for the master plan, falling back to any
    blueprint index. Priority groups (first non-empty wins; within a
    group sort by mtime descending):

      1. .kaizen/docs/<topic>/plan.{json,yaml}          ← workflow plans
      2. .kaizen/docs/plans/*.{json,yaml}                ← legacy flat
      3. .kaizen/docs/<topic>/blueprint.{json,yaml}      ← session-bundle indexes

    The priority ensures a fresh session picks the active workflow
    plan (e.g. unify-artifact-generation.json) over a leaf brainstorm-
    bundle index whose mtime happened to be more recent."""
    cur = Path.cwd().resolve()
    docs_dir = None
    while cur != cur.parent:
        candidate = cur / ".kaizen" / "docs"
        if candidate.is_dir():
            docs_dir = candidate
            break
        cur = cur.parent
    if docs_dir is None:
        return None

    groups: list[list[Path]] = [
        list(docs_dir.glob("*/plan.json"))
        + list(docs_dir.glob("*/plan.yaml"))
        + list(docs_dir.glob("*/plan.yml")),
        list(docs_dir.glob("plans/*.json"))
        + list(docs_dir.glob("plans/*.yaml")),
        list(docs_dir.glob("*/blueprint.json"))
        + list(docs_dir.glob("*/blueprint.yaml")),
    ]
    for group in groups:
        if group:
            group.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return str(group[0])
    return None


def _resolve_file(args_file: str | None) -> str | None:
    """Resolve the target plan file. Priority:
      1. Explicit `args_file` argument
      2. Cached active plan (st.get_active())
      3. Auto-discovery — most recent plan.{json,yaml} under .kaizen/docs/
    Returns None only when no plan can be found anywhere."""
    if args_file:
        return args_file
    active = st.get_active()
    if active is not None:
        state = st._read_cache()
        return state.get("active")
    # Fresh session fallback — find the most recent plan
    return _auto_discover_plan()


# ─── subcommands ────────────────────────────────────────────────────────

def cmd_show(args: argparse.Namespace) -> int:
    """show [file] [N | --id ID] [--subtree[=H]] [--md]

    Smart positional: if `file` looks like an integer (cache scenario:
    `show 5` means items[5] of active plan), shift it into `index` and
    resolve `file` from cache."""
    if args.file is not None and args.index is None:
        try:
            maybe_index = int(args.file)
            # Only treat as index if the string DOESN'T look like a path
            # AND active plan exists. A literal "0" is the canonical case.
            if "/" not in args.file and "." not in args.file:
                target_from_cache = _resolve_file(None)
                if target_from_cache:
                    args.index = maybe_index
                    args.file = None
        except ValueError:
            pass
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache; "
              "pass <file> or run `list <file>` first", file=sys.stderr)
        return 2
    # Touch the cache (refreshes if stale, marks active)
    st.touch(target)
    if args.subtree is not None:
        if not args.id:
            print("--subtree requires --id", file=sys.stderr)
            return 2
        result = bp.read_subtree(target, args.id, hops=args.subtree)
        if args.md:
            out = _render_item_md(result["root"])
            for it in result["linked"]:
                out += "\n---\n\n" + _render_item_md(it)
            print(out)
        else:
            json.dump(result, sys.stdout, indent=2)
            print()
        return 0
    if args.index is not None:
        item = bp.read_item(target, index=args.index)
        out = _render_item_md(item) if args.md else json.dumps(item, indent=2)
        print(out)
        return 0
    if args.id:
        item = bp.read_item(target, id=args.id)
        out = _render_item_md(item) if args.md else json.dumps(item, indent=2)
        print(out)
        return 0
    # Whole plan
    plan = bp.read_plan(target)
    out = _render_md(plan) if args.md else json.dumps(plan, indent=2)
    print(out)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """list [file] — compact one-line-per-item scan. Uses cache when fresh."""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache; "
              "pass <file> first", file=sys.stderr)
        return 2
    entry = st.touch(target)
    rows = entry["items"]  # cache-hit; no source re-parse
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
        return 0
    print(f"{'#':>3}  {'id':10s}  {'kind':12s}  {'status':12s}  title")
    print("-" * 80)
    for r in rows:
        print(
            f"{r['index']:>3}  "
            f"{str(r['id']):10s}  {r['kind']:12s}  "
            f"{r['status']:12s}  {r['title'][:50]}"
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """validate <file> — schema + DAG check."""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    try:
        bp._schema_validate(bp.read_plan(target))
        schema_ok = True
        schema_err = ""
    except Exception as e:
        schema_ok = False
        schema_err = str(e)
    broken = bp.dag_check(target)
    if schema_ok and not broken:
        print("✓ schema PASS")
        print("✓ DAG clean")
        return 0
    if not schema_ok:
        print(f"✗ schema FAIL: {schema_err[:200]}")
    if broken:
        print(f"✗ DAG BROKEN ({len(broken)}):")
        for b in broken:
            print(f"  - {b}")
    return 1


def cmd_set_status(args: argparse.Namespace) -> int:
    """set-status [file] --id X --status S"""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    result = bp.set_item_status(
        target, args.id, args.status, validate=args.validate)
    st.touch(target)  # refresh cache after mutation
    print(f"✓ {args.id}.status: {result['old']} → {result['new']}")
    return 0


def cmd_set_task_status(args: argparse.Namespace) -> int:
    """set-task-status [file] --task-id X --status S"""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    result = bp.set_task_status(
        target, args.task_id, args.status, validate=args.validate)
    st.touch(target)
    print(f"✓ task {args.task_id}.status: {result['old']} → {result['new']}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """scan — pure cache-hit summary of active plan (no source read)."""
    entry = st.get_active()
    if entry is None:
        print("no active plan in cache; run `list <file>` first",
              file=sys.stderr)
        return 2
    if args.json:
        json.dump(entry, sys.stdout, indent=2)
        print()
        return 0
    print(f"project: {entry.get('project')}")
    print(f"summary: {entry.get('summary', '')[:120]}")
    print(f"items:   {entry.get('n_items')}")
    print(f"cached:  {entry.get('cached_at')}")
    h = entry.get("content_hash")
    if h:
        print(f"hash:    {h[:16]}...{h[-8:]}")
    rollup = entry.get("status_rollup", {})
    if rollup:
        print(f"status:  {', '.join(f'{k}={v}' for k,v in sorted(rollup.items()))}")
    rollup = entry.get("kind_rollup", {})
    if rollup:
        print(f"kind:    {', '.join(f'{k}={v}' for k,v in sorted(rollup.items()))}")
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    """state — inspect / clear the cache."""
    if args.clear:
        st.clear(args.clear if args.clear != "all" else None)
        print(f"✓ cache cleared{'' if args.clear == 'all' else f' for {args.clear}'}")
        return 0
    rows = st.list_cached()
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
        return 0
    if not rows:
        print("(cache empty)")
        return 0
    print(f"{'A':1s} {'project':16s} {'items':>5s} {'kb':>5s} {'cached_at':22s} path")
    print("-" * 100)
    for r in rows:
        active = "*" if r["active"] else " "
        print(
            f"{active} {r['project']:16s} {r['n_items']:>5d} "
            f"{r['size_kb']:>5.1f} {r['cached_at']:22s} {r['path']}"
        )
    return 0


def _next_item_id(target: str) -> str:
    """Pick the next unused 2-digit id (01..99)."""
    plan = bp.read_plan(target)
    used = {it.get("id") for it in plan.get("items", [])}
    for i in range(1, 100):
        candidate = f"{i:02d}"
        if candidate not in used:
            return candidate
    # Fall back to numeric beyond 99
    return str(max((int(u) for u in used if u and u.isdigit()),
                   default=0) + 1)


def _next_task_id(target: str, list_id: str) -> str:
    """Pick the next task id like '<list-id>.<n>' for an existing list."""
    plan = bp.read_plan(target)
    item = next((i for i in plan.get("items", []) if i.get("id") == list_id),
                None)
    if not item:
        raise KeyError(f"no item with id={list_id!r}")
    used = {t.get("id") for t in (item.get("tasks") or [])}
    n = 1
    while f"{list_id}.{n}" in used:
        n += 1
    return f"{list_id}.{n}"


def cmd_add_item(args: argparse.Namespace) -> int:
    """add-item [file] --kind K --title T [--id I] [--parent P]
                                [--status S] [--summary X] [--owner O]
                                [--tags T1,T2]"""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    item_id = args.id or _next_item_id(target)
    import datetime
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    new_item = {
        "id": item_id,
        "kind": args.kind,
        "title": args.title,
        "status": args.status,
        "summary": args.summary or "",
        "created": today,
        "updated": today,
        "tags": [t.strip() for t in args.tags.split(",")] if args.tags else [],
        "owner": args.owner or "agent",
        "links": {
            "parents": [args.parent] if args.parent else [],
            "children": [],
            "related": [],
            "supersedes": [],
            "superseded_by": None,
        },
        "content": None,
        "content_ref": None,
        "tasks": [] if args.kind == "task-list" else None,
        "outcome": None,
        "confidence": None,
        "sources": [],
        "meta": {},
    }
    bp.add_item(target, new_item, validate=args.validate)
    # Auto-link parent's children
    if args.parent:
        plan = bp.read_plan(target)
        for it in plan["items"]:
            if it.get("id") == args.parent:
                children = it.setdefault("links", {}).setdefault("children", [])
                if item_id not in children:
                    children.append(item_id)
                break
        from _atomic import atomic_write_json
        atomic_write_json(target, plan, sort_keys=False)
    st.touch(target)
    print(f"✓ added item {item_id} (kind={args.kind})")
    return 0


def cmd_add_task(args: argparse.Namespace) -> int:
    """add-task [file] --to <list-id> --subject S
                                [--id I] [--status S] [--owner O]
                                [--blocked-by B1,B2] [--refs R1,R2]
                                [--tags T1,T2]"""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    task_id = args.id or _next_task_id(target, args.to)
    new_task = {
        "id": task_id,
        "subject": args.subject,
        "status": args.status,
        "owner": args.owner or "agent",
        "blocked_by": ([b.strip() for b in args.blocked_by.split(",")]
                       if args.blocked_by else []),
        "refs": [r.strip() for r in args.refs.split(",")] if args.refs else [],
        "tags": [t.strip() for t in args.tags.split(",")] if args.tags else [],
    }
    bp.add_task(target, args.to, new_task, validate=args.validate)
    st.touch(target)
    print(f"✓ added task {task_id} to list {args.to}")
    return 0


def cmd_verify_hash(args: argparse.Namespace) -> int:
    """verify-hash [file] — content_hash drift check."""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    result = bp.verify_hash(target)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0 if result["ok"] else 1
    if result["first_read"]:
        print("⚠ no stored hash — file not yet rewritten through the CLI")
        print(f"  computed: {result['computed']}")
        return 1
    if result["ok"]:
        print(f"✓ hash matches: {result['stored'][:16]}...")
        return 0
    print(f"✗ DRIFT detected")
    print(f"  stored:   {result['stored']}")
    print(f"  computed: {result['computed']}")
    return 1


def cmd_resume(args: argparse.Namespace) -> int:
    """resume [file] — pick the next actionable task."""
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    st.touch(target)
    result = bp.resume(target)
    if result is None:
        print("(no actionable task — every task completed/skipped/blocked)")
        return 0
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0
    item, task = result["item"], result["task"]
    print(f"item:   {item.get('id')} — {item.get('title', '')[:70]}")
    print(f"task:   {task.get('id')} — {task.get('subject', '')[:70]}")
    print(f"status: {task.get('status')}")
    if task.get("blocked_by"):
        print(f"deps:   {', '.join(task['blocked_by'])} (all clear)")
    if task.get("refs"):
        print(f"refs:   {', '.join(task['refs'][:3])}")
    print(f"why:    {result['reason']}")
    return 0


def cmd_chunk(args: argparse.Namespace) -> int:
    """chunk [file] --list-id X [--subagents] — chunk a task-list.

    DEFAULT (no --subagents): parent walks 3 tasks per chunk; commit /
    verify between chunks. No Agent() dispatch.

    With --subagents: apply the parallel-branches kit's D2 rubric:
      ≤3 in-flight  → PARENT_DOES_IT  (no dispatch)
      4-6           → ONE_SUBAGENT    (one Agent() call)
      7-30          → GRID            (ceil(n/3) chunks, 2-3 tasks each)
      31+           → POOL            (queue-picker; out of CLI scope)
    """
    target = _resolve_file(args.file)
    if not target:
        print("no plan given and no active plan in cache", file=sys.stderr)
        return 2
    st.touch(target)
    result = bp.chunk_tasks(target, args.list_id, subagents=args.subagents)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0
    # Human-readable summary
    print(f"task-list:     {args.list_id}")
    print(f"bucket:        {result['bucket']}")
    print(f"in-flight:     {result['n_tasks']} tasks")
    print(f"chunks:        {result['n_chunks']}")
    dh = result["dispatch_hint"]
    print(
        f"dispatch:      mode={dh['mode']}  isolation={dh['isolation']}  "
        f"agent={dh['agent']}"
    )
    print(f"rationale:     {result['rationale']}")
    if result["chunks"]:
        print()
        print("chunks:")
        for ci, chunk in enumerate(result["chunks"]):
            ids = [t.get("id", "?") for t in chunk]
            print(f"  chunk {ci + 1}: [{', '.join(ids)}]")
            for t in chunk:
                print(f"    - {t.get('id')}  {t.get('subject', '')[:60]}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """init <file> --topic T [--project P] — create from template."""
    # Locate the template
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent.parent.parent
    template = (
        repo_root / ".kaizen" / "docs" / "templates" / "blueprint-template.json"
    )
    if not template.is_file():
        print(f"template not found at {template}", file=sys.stderr)
        return 2
    text = template.read_text(encoding="utf-8")
    # Fill placeholders
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    project = args.project or "kaizen-md"
    text = (
        text.replace("<project-slug>", project)
            .replace("<YYYY-MM-DDTHH:MM:SSZ>", now)
            .replace("<YYYY-MM-DD>", today)
            .replace("<root plan title>", args.topic)
            .replace(
                "<one-line description — what this blueprint tracks>",
                f"{args.topic}")
    )
    # Parse + atomic write to ensure the result is valid JSON
    data = json.loads(text)
    from _atomic import atomic_write_json
    atomic_write_json(args.file, data, sort_keys=False)
    st.touch(args.file)  # mark active so subsequent calls infer the path
    print(f"✓ wrote {args.file}")
    return 0


# ─── main ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-blueprint",
        description="1-roundtrip blueprint plan management",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("show", help="read whole plan or one item")
    sp.add_argument("file", nargs="?", default=None,
                    help="omit to use active plan from cache")
    sp.add_argument("index", nargs="?", type=int, default=None,
                    help="items[N] by array index (positional)")
    sp.add_argument("--id", default=None, help="items[?].id == ID")
    sp.add_argument("--subtree", nargs="?", type=int, const=1, default=None,
                    help="--subtree=H follows links.children H hops")
    sp.add_argument("--md", action="store_true", help="render as markdown")
    sp.set_defaults(func=cmd_show)

    lp = sub.add_parser("list", help="compact scan of items (cache-hit)")
    lp.add_argument("file", nargs="?", default=None,
                    help="omit to use active plan from cache")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_list)

    scp = sub.add_parser("scan",
                         help="pure cache-hit summary of active plan")
    scp.add_argument("--json", action="store_true")
    scp.set_defaults(func=cmd_scan)

    stp = sub.add_parser("state",
                         help="inspect / clear the cache")
    stp.add_argument("--json", action="store_true")
    stp.add_argument("--clear", nargs="?", const="all", default=None,
                     help="--clear (all) or --clear <path>")
    stp.set_defaults(func=cmd_state)

    vp = sub.add_parser("validate", help="schema + DAG check")
    vp.add_argument("file", nargs="?", default=None)
    vp.set_defaults(func=cmd_validate)

    ssp = sub.add_parser("set-status", help="atomic item-status flip")
    ssp.add_argument("file", nargs="?", default=None)
    ssp.add_argument("--id", required=True)
    ssp.add_argument("--status", required=True,
                     choices=["draft", "active", "shipped", "parked",
                              "superseded", "blocked"])
    ssp.add_argument("--validate", action="store_true",
                     help="schema-check before writing")
    ssp.set_defaults(func=cmd_set_status)

    sttp = sub.add_parser("set-task-status",
                          help="atomic task-status flip")
    sttp.add_argument("file", nargs="?", default=None)
    sttp.add_argument("--task-id", required=True)
    sttp.add_argument("--status", required=True,
                      choices=["pending", "in_progress", "completed",
                               "blocked", "skipped"])
    sttp.add_argument("--validate", action="store_true")
    sttp.set_defaults(func=cmd_set_task_status)

    aip = sub.add_parser("add-item",
                         help="append a new item to items[]")
    aip.add_argument("file", nargs="?", default=None)
    aip.add_argument("--kind", required=True,
                     choices=["plan", "research", "idea", "task-list",
                              "spec", "decision", "note", "audit", "brainstorm"])
    aip.add_argument("--title", required=True)
    aip.add_argument("--id", default=None, help="auto-picked if omitted")
    aip.add_argument("--parent", default=None,
                     help="auto-links parent's links.children")
    aip.add_argument("--status", default="draft",
                     choices=["draft", "active", "shipped", "parked",
                              "superseded", "blocked"])
    aip.add_argument("--summary", default=None)
    aip.add_argument("--owner", default=None)
    aip.add_argument("--tags", default=None, help="comma-separated")
    aip.add_argument("--validate", action="store_true")
    aip.set_defaults(func=cmd_add_item)

    atp = sub.add_parser("add-task",
                         help="append a task to a kind=task-list item")
    atp.add_argument("file", nargs="?", default=None)
    atp.add_argument("--to", required=True, help="task-list item id")
    atp.add_argument("--subject", required=True)
    atp.add_argument("--id", default=None, help="auto-picked if omitted")
    atp.add_argument("--status", default="pending",
                     choices=["pending", "in_progress", "completed",
                              "blocked", "skipped"])
    atp.add_argument("--owner", default=None)
    atp.add_argument("--blocked-by", default=None, help="comma-separated")
    atp.add_argument("--refs", default=None, help="comma-separated")
    atp.add_argument("--tags", default=None, help="comma-separated")
    atp.add_argument("--validate", action="store_true")
    atp.set_defaults(func=cmd_add_task)

    vhp = sub.add_parser("verify-hash",
                         help="content_hash drift check")
    vhp.add_argument("file", nargs="?", default=None)
    vhp.add_argument("--json", action="store_true")
    vhp.set_defaults(func=cmd_verify_hash)

    rp = sub.add_parser("resume",
                        help="pick the next actionable task")
    rp.add_argument("file", nargs="?", default=None)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)

    cp = sub.add_parser("chunk",
                        help="chunk a task-list (default: 3-task parent batches)")
    cp.add_argument("file", nargs="?", default=None)
    cp.add_argument("--list-id", required=True,
                    help="id of the kind=task-list item to chunk")
    cp.add_argument("--subagents", action="store_true",
                    help="opt into the D2 rubric for subagent dispatch")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_chunk)

    ip = sub.add_parser("init", help="create from template")
    ip.add_argument("file")
    ip.add_argument("--topic", required=True)
    ip.add_argument("--project", default=None)
    ip.set_defaults(func=cmd_init)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
