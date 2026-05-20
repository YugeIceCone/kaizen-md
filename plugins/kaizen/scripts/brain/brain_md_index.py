# consolidated-cli-parent: brain

"""kaizen brain markdown index — human/agent-readable brain inventory.

Port of upstream ``remember-md/remember/scripts/build-index.js``. Walks
``brain/{People,Projects,Areas,Notes,Tasks,Journal}`` and emits a
markdown index (tables in ``format_full``; one-line per category in
``format_compact``).

**Distinct from** ``scripts/indexers/build_index.py`` (the SQLite +
sentence-transformers SEMANTIC index). Both coexist:

  - ``build_index.py``      → semantic search backbone (k-NN over
                              embeddings). DB-backed. For `kaizen-brain
                              search`.
  - ``brain_md_index.py``   → entity inventory for capture routing.
                              Plain markdown. For build_context.py's
                              UserPromptSubmit injection.

## CLI

::

   kaizen-brain-md-index             # full markdown tables
   kaizen-brain-md-index --compact   # one-line per category
   kaizen-brain-md-index --brain PATH
   kaizen-brain-md-index --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import _brain  # noqa: E402

# ─── Scanners (return list[dict]) ────────────────────────────────────

def _title_from_stem(stem: str) -> str:
    """``pref-foo-bar`` → ``Pref Foo Bar`` for human-readable
    display when no `name:` in frontmatter."""
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), stem.replace("-", " "))

def _frontmatter_only(path: Path) -> dict:
    """Lightweight frontmatter read (max 2KB) for index scans. Avoids
    re-parsing whole files just to extract a few metadata fields.

    PyYAML auto-converts ISO dates to ``datetime.date`` objects;
    upstream JS keeps everything as strings. To match upstream's
    string-everything contract for index output, ``_str_coerce`` is
    applied to scalar values."""
    try:
        with path.open("rb") as f:
            buf = f.read(2048)
    except OSError:
        return {}
    text = buf.decode("utf-8", errors="replace")
    fm, _body = _brain.parse_note(text)
    # Pull the H1 title separately — _brain.parse_note doesn't preserve it
    h1 = re.search(r"^#\s+(.+)$", text, re.M)
    if h1:
        fm["_title"] = h1.group(1).strip()
    return fm

def _str_coerce(v) -> str:
    """Coerce a scalar frontmatter value to its string form for the
    markdown index output. ``datetime.date`` → ISO 8601, lists →
    comma-separated, everything else → ``str(v)`` (None becomes '')."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return ", ".join(_str_coerce(x) for x in v)
    return str(v)

def scan_people(brain: Path) -> list[dict]:
    d = brain / "People"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.suffix != ".md":
            continue
        m = _frontmatter_only(f)
        stem = f.stem
        out.append({
            "file": stem,
            "name": m.get("_title") or _title_from_stem(stem),
            "role": _str_coerce(m.get("role")),
            "org": _str_coerce(m.get("org") or m.get("organization")),
            "last_contact": _str_coerce(m.get("last_contact") or m.get("updated")),
            "tags": _str_coerce(m.get("tags")),
        })
    return out

def scan_projects(brain: Path) -> list[dict]:
    d = brain / "Projects"
    if not d.is_dir():
        return []
    out = []
    for sub in sorted(d.iterdir()):
        if not sub.is_dir():
            continue
        main_file = sub / f"{sub.name}.md"
        if not main_file.is_file():
            mds = sorted(p for p in sub.iterdir() if p.is_file() and p.suffix == ".md")
            if not mds:
                continue
            main_file = mds[0]
        m = _frontmatter_only(main_file)
        sub_count = sum(1 for p in sub.iterdir() if p.is_file() and p.suffix == ".md") - 1
        out.append({
            "file": sub.name,
            "name": m.get("_title") or _title_from_stem(sub.name),
            "status": _str_coerce(m.get("status")),
            "tags": _str_coerce(m.get("tags")),
            "updated": _str_coerce(m.get("updated")),
            "sub_notes": max(0, sub_count),
        })
    return out

def scan_areas(brain: Path) -> list[dict]:
    d = brain / "Areas"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.suffix != ".md":
            continue
        m = _frontmatter_only(f)
        stem = f.stem
        out.append({
            "file": stem,
            "name": m.get("_title") or _title_from_stem(stem),
            "updated": _str_coerce(m.get("updated")),
        })
    return out

def scan_notes(brain: Path) -> list[dict]:
    d = brain / "Notes"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.suffix != ".md":
            continue
        m = _frontmatter_only(f)
        stem = f.stem
        out.append({
            "file": stem,
            "name": m.get("_title") or _title_from_stem(stem),
            "tags": _str_coerce(m.get("tags")),
            "created": _str_coerce(m.get("created")),
        })
    return out

def scan_tasks(brain: Path) -> dict:
    """Count items in brain/Tasks/tasks.md per section. Returns
    ``{focus, next_up, backlog, done}``."""
    counts = {"focus": 0, "next_up": 0, "backlog": 0, "done": 0}
    tasks_file = brain / "Tasks" / "tasks.md"
    if not tasks_file.is_file():
        return counts
    try:
        text = tasks_file.read_text(encoding="utf-8")
    except OSError:
        return counts

    current = None
    for line in text.split("\n"):
        lower = line.strip().lower()
        if lower.startswith("## focus"):
            current = "focus"
        elif lower.startswith("## next up"):
            current = "next_up"
        elif lower.startswith("## backlog"):
            current = "backlog"
        elif lower.startswith("## done") or lower.startswith("## completed"):
            current = "done"
        elif lower.startswith("## "):
            current = None
        elif current and re.match(r"^-\s*\[.\]", line.strip()):
            counts[current] += 1
    return counts

def scan_journal(brain: Path) -> dict:
    d = brain / "Journal"
    if not d.is_dir():
        return {"count": 0, "latest": ""}
    entries = sorted(
        f.name for f in d.iterdir()
        if f.is_file() and f.suffix == ".md"
    )
    return {
        "count": len(entries),
        "latest": entries[-1][:-3] if entries else "",
    }

# ─── Formatters ───────────────────────────────────────────────────────

def format_full(brain: Path) -> str:
    """Markdown tables — one section per category. For human reading."""
    lines = [f"# Knowledge Index\n**Brain:** `{brain}`\n"]

    people = scan_people(brain)
    if people:
        lines.append("## People\n| Name | Role/Org | Last Contact | Tags |")
        lines.append("|------|----------|--------------|------|")
        for p in people:
            org = p["role"] + (f" @ {p['org']}" if p["org"] else "")
            lines.append(
                f"| [[People/{p['file']}\\|{p['name']}]] | {org} | "
                f"{p['last_contact']} | {p['tags']} |"
            )
    else:
        lines.append("## People\n*None yet*")
    lines.append("")

    projects = scan_projects(brain)
    if projects:
        lines.append("## Projects\n| Name | Status | Updated | Sub-notes | Tags |")
        lines.append("|------|--------|---------|-----------|------|")
        for p in projects:
            lines.append(
                f"| [[Projects/{p['file']}/{p['file']}\\|{p['name']}]] | "
                f"{p['status']} | {p['updated']} | {p['sub_notes']} | {p['tags']} |"
            )
    else:
        lines.append("## Projects\n*None yet*")
    lines.append("")

    areas = scan_areas(brain)
    if areas:
        lines.append("## Areas\n| Name | Updated |")
        lines.append("|------|---------|")
        for a in areas:
            lines.append(f"| [[Areas/{a['file']}\\|{a['name']}]] | {a['updated']} |")
    else:
        lines.append("## Areas\n*None yet*")
    lines.append("")

    notes = scan_notes(brain)
    if notes:
        lines.append(f"## Notes ({len(notes)} total)\n| Name | Tags | Created |")
        lines.append("|------|------|---------|")
        for n in notes:
            lines.append(f"| [[Notes/{n['file']}\\|{n['name']}]] | {n['tags']} | {n['created']} |")
    else:
        lines.append("## Notes\n*None yet*")
    lines.append("")

    tasks = scan_tasks(brain)
    lines.append(f"## Tasks\n- **Focus:** {tasks['focus']} items")
    lines.append(f"- **Next Up:** {tasks['next_up']} items")
    lines.append(f"- **Backlog:** {tasks['backlog']} items")
    lines.append(f"- **Done:** {tasks['done']} items")
    lines.append("")

    journal = scan_journal(brain)
    lines.append(f"## Journal\n- **Entries:** {journal['count']}")
    if journal["latest"]:
        lines.append(f"- **Latest:** {journal['latest']}")

    return "\n".join(lines)

def format_compact(brain: Path) -> str:
    """One-line per category. For LLM context injection — cheap +
    routing-friendly. Mirrors upstream build-index.js::formatCompact."""
    people_files = [p["file"] for p in scan_people(brain)]
    project_files = [p["file"] for p in scan_projects(brain)]
    area_files = [a["file"] for a in scan_areas(brain)]
    note_files = [n["file"] for n in scan_notes(brain)]
    tasks = scan_tasks(brain)
    journal = scan_journal(brain)

    notes_preview = note_files[:20]
    notes_tail = "..." if len(note_files) > 20 else ""

    return "\n".join([
        f"BRAIN INDEX ({brain})",
        f"People: {', '.join(people_files) or 'none'}",
        f"Projects: {', '.join(project_files) or 'none'}",
        f"Areas: {', '.join(area_files) or 'none'}",
        f"Notes ({len(note_files)}): {', '.join(notes_preview) or 'none'}{notes_tail}",
        f"Tasks: {tasks['focus']} focus, {tasks['next_up']} next, {tasks['backlog']} backlog",
        f"Journal: {journal['count']} entries, latest {journal['latest']}",
    ])

# ─── CLI ─────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kaizen-brain-md-index",
        description="Generate markdown brain inventory (full or compact).",
    )
    ap.add_argument("--compact", action="store_true",
                    help="one-line per category (LLM-friendly)")
    ap.add_argument("--brain", type=Path, default=None,
                    help="brain root path (default: $KAIZEN_BRAIN_DIR)")
    ap.add_argument("--json", action="store_true",
                    help="emit structured envelope on stdout")
    args = ap.parse_args(argv)

    if os.environ.get("KAIZEN_BRAIN_MD_INDEX_DISABLE") == "1":
        sys.stderr.write("kaizen-brain-md-index: disabled\n")
        return 0

    brain = args.brain or _brain.brain_root()
    if not brain.is_dir():
        sys.stderr.write(f"brain not found at {brain}\n")
        return 1

    if args.json:
        data = {
            "brain": str(brain),
            "people": scan_people(brain),
            "projects": scan_projects(brain),
            "areas": scan_areas(brain),
            "notes": scan_notes(brain),
            "tasks": scan_tasks(brain),
            "journal": scan_journal(brain),
        }
        sys.stdout.write(json.dumps({
            "data": data,
            "kaizen": {
                "command": "brain_md_index.py",
                "tool": "kaizen-brain-md-index",
                "tool_version": "1.0.0",
                "schema_version": 1,
            },
        }, default=str, indent=2) + "\n")
        return 0

    out = format_compact(brain) if args.compact else format_full(brain)
    sys.stdout.write(out + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
