#!/usr/bin/env python3
"""kaizen backlog — JSON-sourced micro-work tracker.

Single source of truth: `<workflow_dir>/backlog.json`.
Generated view:        `<workflow_dir>/backlog.md` (never hand-edit).

Subcommands:
  list [section]                  Print items (sections: in_flight|next_up|done|parked|all).
  add --title T --probe P --verify V [--section S] [--ref R] [--tags A,B]
                                  Append a new item.
  start <id>                      Move next_up → in_flight (sets started_at).
  tick <id> [--committed SHA]     Move in_flight → done (sets committed_at).
  park <id> --reason R            Move to parked.
  unpark <id> [--section S]       Move parked → next_up (or specified).
  decision --text T [--why Y]     Append a one-liner to ## Decisions.
  render                          Generate the .md view from the .json source.
  verify                          Exit non-zero if .md drifted from .json (CI gate).
  show <id>                       Print one item as JSON.

Config: reads .kaizen.toml at repo root for `backlog_path`.
Path resolution: backlog.json sits alongside backlog.md (same stem).
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
KIND = "kaizen.backlog"
SECTIONS = ["in_flight", "next_up", "done", "parked"]
SECTION_LABELS = {
    "in_flight": "## In flight",
    "next_up":   "## Next up",
    "done":      "## Done (this week)",
    "parked":    "## Parked / deferred",
}


# ─── Config / paths ──────────────────────────────────────────────────

def repo_root() -> Path:
    p = Path.cwd()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    print("backlog: not in a git repo", file=sys.stderr)
    sys.exit(2)


def read_config(root: Path) -> dict:
    cfg = root / ".kaizen.toml"
    out = {"backlog_path": "BACKLOG.md"}
    if not cfg.exists():
        return out
    for line in cfg.read_text().splitlines():
        m = re.match(r'^\s*([a-z_]+)\s*=\s*"?([^"]*)"?\s*(?:#.*)?$', line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def resolve_paths(root: Path):
    cfg = read_config(root)
    md_path = root / cfg.get("backlog_path", "BACKLOG.md")
    json_path = md_path.with_suffix(".json")
    md_path = md_path.with_suffix(".md")
    return json_path, md_path


# ─── Store IO ────────────────────────────────────────────────────────

def empty_store() -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "metadata": {
            "created": now,
            "updated": now,
            "active_workflow_ref": None,
        },
        "items": [],
        "decisions": [],
    }


def load_store(path: Path) -> dict:
    if not path.exists():
        return empty_store()
    data = json.loads(path.read_text())
    # Forward-compat sanity
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("kind", KIND)
    data.setdefault("items", [])
    data.setdefault("decisions", [])
    data.setdefault("metadata", {"created": "", "updated": "", "active_workflow_ref": None})
    return data


def save_store(path: Path, store: dict):
    store["metadata"]["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n")


# ─── Item helpers ────────────────────────────────────────────────────

def next_id(store: dict) -> str:
    nums = [int(m.group(1)) for it in store["items"]
            if (m := re.match(r"^BK-(\d+)$", it.get("id", "")))]
    n = (max(nums) if nums else 0) + 1
    return f"BK-{n:03d}"


def find_item(store: dict, item_id: str) -> dict:
    for it in store["items"]:
        if it["id"] == item_id:
            return it
    print(f"backlog: id not found: {item_id}", file=sys.stderr)
    sys.exit(2)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Subcommands ─────────────────────────────────────────────────────

def cmd_list(store, args):
    section = args.section
    items = store["items"] if section == "all" else [i for i in store["items"] if i["section"] == section]
    if not items:
        print(f"(no items in {section})")
        return
    for it in items:
        flag = "[x]" if it["section"] == "done" else "[ ]"
        print(f"{it['id']}  {flag}  {it['title']}")


def cmd_show(store, args):
    print(json.dumps(find_item(store, args.id), indent=2))


def cmd_add(store, args):
    item = {
        "id": next_id(store),
        "section": args.section,
        "title": args.title,
        "ref": args.ref or None,
        "probe": args.probe,
        "verify": args.verify,
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "started_at": None,
        "committed": None,
        "committed_at": None,
        "parked_reason": None,
        "probe_output": None,
    }
    store["items"].append(item)
    print(f"added {item['id']} → {item['section']}")
    return item


def cmd_start(store, args):
    it = find_item(store, args.id)
    it["section"] = "in_flight"
    it["started_at"] = now_utc()
    print(f"{args.id} → in_flight")


def cmd_tick(store, args):
    it = find_item(store, args.id)
    it["section"] = "done"
    it["committed"] = args.committed
    it["committed_at"] = now_utc()
    print(f"{args.id} → done")


def cmd_park(store, args):
    it = find_item(store, args.id)
    it["section"] = "parked"
    it["parked_reason"] = args.reason
    print(f"{args.id} → parked: {args.reason}")


def cmd_unpark(store, args):
    it = find_item(store, args.id)
    it["section"] = args.section
    it["parked_reason"] = None
    print(f"{args.id} → {args.section}")


def cmd_decision(store, args):
    store["decisions"].append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "text": args.text,
        "why": args.why or "",
    })
    print(f"decision recorded: {args.text}")


# ─── Render (.json → .md) ───────────────────────────────────────────

def fmt_item(it: dict) -> str:
    check = "[x]" if it["section"] == "done" else "[ ]"
    line = f"- {check} **{it['id']}** {it['title']}"
    if it.get("ref"):
        line += f" *({it['ref']})*"
    parts = []
    if it.get("probe"):  parts.append(f"probe: `{it['probe']}`")
    if it.get("verify"): parts.append(f"verify: `{it['verify']}`")
    if it["section"] == "done" and it.get("committed"):
        parts.append(f"committed: `{it['committed'][:9]}`")
    if it["section"] == "parked" and it.get("parked_reason"):
        parts.append(f"parked: {it['parked_reason']}")
    if parts:
        line += " — " + " — ".join(parts)
    if it.get("tags"):
        line += f"  `[{' '.join(it['tags'])}]`"
    return line


def render_md(store: dict) -> str:
    out = ["# Backlog", ""]
    out.append("> Generated from `backlog.json`. **Do not edit this file** — use")
    out.append("> `~/.claude/skills/workflow/scripts/backlog.py {add|start|tick|park|render}`.")
    out.append("> Schema: `kaizen.backlog` v1.")
    out.append("")
    for sec in SECTIONS:
        out.append(SECTION_LABELS[sec])
        out.append("")
        items = [i for i in store["items"] if i["section"] == sec]
        if not items:
            out.append("_(none)_")
        else:
            for it in items:
                out.append(fmt_item(it))
        out.append("")
    if store["decisions"]:
        out.append("## Decisions")
        out.append("")
        for d in store["decisions"]:
            line = f"- **{d['date']}** — {d['text']}"
            if d.get("why"):
                line += f" — *{d['why']}*"
            out.append(line)
        out.append("")
    return "\n".join(out)


def cmd_render(store, args, *, json_path: Path, md_path: Path):
    md = render_md(store)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md)
    # Persist .json too so a fresh `render` seeds both files (setup.sh path).
    if not json_path.exists():
        save_store(json_path, store)
    print(f"rendered → {md_path}")


def cmd_verify(store, args, *, json_path: Path, md_path: Path):
    expected = render_md(store)
    if not md_path.exists():
        print(f"verify: {md_path} missing — run render", file=sys.stderr)
        sys.exit(1)
    actual = md_path.read_text()
    if expected.rstrip() != actual.rstrip():
        print(f"verify: {md_path} drifted from {json_path} — run render", file=sys.stderr)
        sys.exit(1)
    print(f"verify: ok ({md_path} matches {json_path})")


# ─── CLI ─────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(prog="backlog", description=__doc__.split("\n")[0])
    # Subcommand is optional; bare invocation (e.g. /kaizen:backlog with
    # no args) defaults to `list all`. Avoids the slash-command iron-law
    # forbidding ${ARGUMENTS:-defaults-with-spaces}.
    sp = p.add_subparsers(dest="cmd", required=False)

    p_list = sp.add_parser("list")
    p_list.add_argument("section", nargs="?", default="all",
                        choices=SECTIONS + ["all"])

    p_show = sp.add_parser("show")
    p_show.add_argument("id")

    p_add = sp.add_parser("add")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--probe", required=True)
    p_add.add_argument("--verify", required=True)
    p_add.add_argument("--section", default="next_up", choices=SECTIONS)
    p_add.add_argument("--ref", default=None)
    p_add.add_argument("--tags", default=None, help="comma-separated")

    p_start = sp.add_parser("start"); p_start.add_argument("id")
    p_tick = sp.add_parser("tick")
    p_tick.add_argument("id")
    p_tick.add_argument("--committed", default=None, help="commit sha (short)")
    p_park = sp.add_parser("park")
    p_park.add_argument("id")
    p_park.add_argument("--reason", required=True)
    p_unpark = sp.add_parser("unpark")
    p_unpark.add_argument("id")
    p_unpark.add_argument("--section", default="next_up", choices=SECTIONS)

    p_dec = sp.add_parser("decision")
    p_dec.add_argument("--text", required=True)
    p_dec.add_argument("--why", default=None)

    sp.add_parser("render")
    sp.add_parser("verify")
    return p


def main():
    args = build_parser().parse_args()
    # No subcommand → default to `list all` (avoids ${ARGUMENTS:-list all}
    # in the slash command, which iron-law forbids — spaces in default).
    if args.cmd is None:
        args.cmd = "list"
        args.section = "all"
    root = repo_root()
    json_path, md_path = resolve_paths(root)
    store = load_store(json_path)

    mutating = args.cmd in {"add", "start", "tick", "park", "unpark", "decision"}

    if args.cmd == "list":     cmd_list(store, args)
    elif args.cmd == "show":   cmd_show(store, args)
    elif args.cmd == "add":    cmd_add(store, args)
    elif args.cmd == "start":  cmd_start(store, args)
    elif args.cmd == "tick":   cmd_tick(store, args)
    elif args.cmd == "park":   cmd_park(store, args)
    elif args.cmd == "unpark": cmd_unpark(store, args)
    elif args.cmd == "decision": cmd_decision(store, args)
    elif args.cmd == "render": cmd_render(store, args, json_path=json_path, md_path=md_path)
    elif args.cmd == "verify": cmd_verify(store, args, json_path=json_path, md_path=md_path)

    if mutating:
        save_store(json_path, store)
        # Auto-render so the .md view stays in sync
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_md(store))


if __name__ == "__main__":
    main()
