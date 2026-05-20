#!/usr/bin/env python3
# consolidated-cli-parent: roadmap
"""kaizen roadmap-status — parse phase-progress tables out of a handoff
markdown file and render a progress dashboard.

The source of truth is the markdown file at `plans/<date>-handoff.md`.
This script:

  1. Locates the handoff (newest matching `plans/*handoff*.md` in cwd).
  2. Parses every `## Phase N — <title>` heading and its table.
  3. Reads the status column for each row (✅ done / ⬜ pending / etc.).
  4. Renders progress bars + counts + the next-up item.

Single-source-of-truth principle: status lives in the handoff. Nothing
to sync between a separate config and the doc. Updating the handoff
to ✅ an item automatically updates the renderer's output.

## CLI

    roadmap_status.py progress           text dashboard (default)
    roadmap_status.py progress --json    structured JSON output
    roadmap_status.py next               next pending item only
    roadmap_status.py phases             list phase names + counts
    roadmap_status.py phase <N>          single phase detail
    roadmap_status.py path               resolved handoff path

## Env

    KAIZEN_ROADMAP_HANDOFF — explicit handoff path override (skip auto-detect)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
from pathlib import Path

# Canonical tool-output envelope — see assets/schemas/tool-output.schema.json
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "io"))
import _envelope  # noqa: E402

_emit_roadmap = _envelope.emitter("kaizen-roadmap", tool_version="1.0.0")

# ─── Constants ────────────────────────────────────────────────────────

BAR_LENGTH = 12
BAR_FILLED = "█"
BAR_EMPTY = "░"
DONE_MARKER = "✅"
PENDING_MARKER = "⬜"

# ─── Data ─────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Item:
    item_id: str
    title: str
    status: str          # 'done' | 'pending' | 'unknown'
    commit: str = ""
    raw_status: str = ""  # original status-cell text

@dataclasses.dataclass
class Phase:
    number: int
    title: str
    items: list[Item]

    @property
    def done(self) -> int:
        return sum(1 for it in self.items if it.status == "done")

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def pct(self) -> float:
        if not self.items:
            return 0.0
        return 100.0 * self.done / self.total

# ─── Handoff resolution ───────────────────────────────────────────────

def resolve_handoff_path() -> Path | None:
    """Find the handoff file: env override → newest `plans/*handoff*.md`
    in cwd → None when absent. Returns absolute path."""
    env = os.environ.get("KAIZEN_ROADMAP_HANDOFF")
    if env:
        p = Path(env).expanduser()
        return p.resolve() if p.is_file() else None
    plans = Path.cwd() / "plans"
    if not plans.is_dir():
        return None
    candidates = sorted(
        (p for p in plans.glob("*handoff*.md")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0].resolve() if candidates else None

# ─── Parser ───────────────────────────────────────────────────────────

_PHASE_HEADING = re.compile(
    r"^##\s+Phase\s+(\d+)\s*[—\-:]\s*(.+?)\s*$", re.MULTILINE
)
# Table rows: `| col1 | col2 | ... |`. Matches data rows only (not header
# row or `|---|` separator).
_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)
_COMMIT_RE = re.compile(r"`([0-9a-f]{7,40})`")

def _row_cells(row: str) -> list[str]:
    """Split a markdown table row body into trimmed cells."""
    return [c.strip() for c in row.split("|")]

def _classify_status(cell: str) -> tuple[str, str]:
    """Return (status, commit_sha). status ∈ {done, pending, unknown}."""
    text = cell.strip()
    lower = text.lower()
    commit = ""
    m = _COMMIT_RE.search(text)
    if m:
        commit = m.group(1)
    if "✅" in text or "done" in lower or "complete" in lower:
        return "done", commit
    if "⬜" in text or "pending" in lower or "start here" in lower or "after " in lower or "independent" in lower:
        return "pending", commit
    return "unknown", commit

def parse_phases(text: str) -> list[Phase]:
    """Pull every `## Phase N — <title>` section + its FIRST following
    table. Skips any phase without a table (e.g. a heading-only section)."""
    phases: list[Phase] = []
    headings = list(_PHASE_HEADING.finditer(text))
    for i, m in enumerate(headings):
        number = int(m.group(1))
        title = m.group(2).strip()
        section_start = m.end()
        section_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        # Stop at the next top-level / level-2 heading that ISN'T a phase
        next_h2 = re.search(
            r"^##\s+(?!Phase\b)", text[section_start:section_end], re.MULTILINE
        )
        if next_h2:
            section_end = section_start + next_h2.start()
        section = text[section_start:section_end]
        items = _parse_table_items(section)
        if items:
            phases.append(Phase(number=number, title=title, items=items))
    return phases

def _parse_table_items(section: str) -> list[Item]:
    """Pull rows from the first markdown table in `section`. Each row's
    columns are [#, Item, File(s), Status]. We're tolerant of column
    presence — just need first + last to extract id + status."""
    items: list[Item] = []
    rows = _TABLE_ROW.findall(section)
    seen_header = False
    for body in rows:
        cells = _row_cells(body)
        # Trim empty leading/trailing produced by `|...|` framing
        cells = [c for c in cells if c != ""] if all(
            c == "" for c in cells[:1] + cells[-1:]
        ) else cells
        # Skip the separator row (`---`).
        if all(re.fullmatch(r"-+", c.replace(":", "")) for c in cells if c):
            continue
        # Skip the header row (best-effort: contains 'Item' or 'Status').
        if not seen_header:
            joined = " ".join(cells).lower()
            if "item" in joined or "status" in joined:
                seen_header = True
                continue
        # Need at least 2 columns — id + status (we accept whatever lies
        # between as "title / file annotations").
        if len(cells) < 2:
            continue
        item_id = cells[0].strip()
        status_cell = cells[-1]
        # Title is the second column when present, else the id itself.
        title = cells[1].strip() if len(cells) >= 3 else item_id
        status, commit = _classify_status(status_cell)
        items.append(Item(
            item_id=item_id,
            title=title,
            status=status,
            commit=commit,
            raw_status=status_cell.strip(),
        ))
    return items

# ─── Rendering ────────────────────────────────────────────────────────

def _bar(done: int, total: int, width: int = BAR_LENGTH) -> str:
    if total == 0:
        return BAR_EMPTY * width
    filled = round(width * done / total)
    filled = max(0, min(width, filled))
    return BAR_FILLED * filled + BAR_EMPTY * (width - filled)

def find_next_pending(phases: list[Phase]) -> Item | None:
    for p in phases:
        for it in p.items:
            if it.status == "pending":
                return it
    return None

def render_dashboard(phases: list[Phase]) -> str:
    if not phases:
        return "(no phase tables found in handoff)"
    lines: list[str] = []
    width = max(len(f"Phase {p.number} — {p.title}") for p in phases)
    width = min(width, 50)
    total_done = 0
    total_items = 0
    for p in phases:
        total_done += p.done
        total_items += p.total
        label = f"Phase {p.number} — {p.title}"
        if len(label) > width:
            label = label[: width - 1] + "…"
        bar = _bar(p.done, p.total)
        marker = " ✅ COMPLETE" if p.done == p.total and p.total else ""
        lines.append(
            f"{label:<{width}}  {bar} {p.done}/{p.total} "
            f"({int(p.pct)}%){marker}"
        )
    lines.append("─" * (width + 4 + BAR_LENGTH + 16))
    overall_bar = _bar(total_done, total_items)
    overall_pct = int(100 * total_done / total_items) if total_items else 0
    lines.append(
        f"{'Total':<{width}}  {overall_bar} {total_done}/{total_items} "
        f"({overall_pct}%)"
    )
    nxt = find_next_pending(phases)
    if nxt:
        lines.append("")
        lines.append(f"Next up: {nxt.item_id} — {nxt.title}")
    return "\n".join(lines)

def render_phase(phase: Phase) -> str:
    lines = [
        f"Phase {phase.number} — {phase.title}",
        _bar(phase.done, phase.total) + f"  {phase.done}/{phase.total} ({int(phase.pct)}%)",
        "",
    ]
    for it in phase.items:
        icon = (
            DONE_MARKER if it.status == "done"
            else PENDING_MARKER if it.status == "pending"
            else "·"
        )
        commit = f" ({it.commit})" if it.commit else ""
        lines.append(f"  {icon} {it.item_id:<10} {it.title}{commit}")
    return "\n".join(lines)

# ─── CLI ─────────────────────────────────────────────────────────────

def _load_phases() -> tuple[list[Phase], Path | None]:
    p = resolve_handoff_path()
    if p is None:
        return [], None
    return parse_phases(p.read_text()), p

def cmd_progress(args) -> int:
    phases, path = _load_phases()
    if path is None:
        sys.stderr.write("kaizen-roadmap: no handoff file found in plans/\n")
        return 1
    if args.json:
        nxt = find_next_pending(phases)
        out = {
            "handoff": str(path),
            "phases": [
                {
                    "number": p.number,
                    "title": p.title,
                    "done": p.done,
                    "total": p.total,
                    "pct": round(p.pct, 1),
                    "items": [dataclasses.asdict(it) for it in p.items],
                }
                for p in phases
            ],
            "next": dataclasses.asdict(nxt) if nxt else None,
        }
        total_done = sum(p.done for p in phases)
        total = sum(p.total for p in phases)
        _emit_roadmap(out, counts={"phases": len(phases),
                                    "items_done": total_done,
                                    "items_total": total})
    else:
        print(render_dashboard(phases))
    return 0

def cmd_next(args) -> int:
    phases, path = _load_phases()
    if path is None:
        sys.stderr.write("kaizen-roadmap: no handoff file found\n")
        return 1
    nxt = find_next_pending(phases)
    if nxt is None:
        if args.json:
            _emit_roadmap(None, verdict="green",
                          counts={"pending": 0})
        else:
            print("(no pending items — all phases complete)")
        return 0
    if args.json:
        _emit_roadmap(dataclasses.asdict(nxt), verdict="yellow")
    else:
        print(f"{nxt.item_id} — {nxt.title}")
    return 0

def cmd_phases(args) -> int:
    phases, path = _load_phases()
    if path is None:
        sys.stderr.write("kaizen-roadmap: no handoff file found\n")
        return 1
    if args.json:
        _emit_roadmap([
            {"number": p.number, "title": p.title,
             "done": p.done, "total": p.total}
            for p in phases
        ], counts={"phases": len(phases)})
    else:
        for p in phases:
            print(f"Phase {p.number} — {p.title}: {p.done}/{p.total}")
    return 0

def cmd_phase(args) -> int:
    phases, path = _load_phases()
    if path is None:
        sys.stderr.write("kaizen-roadmap: no handoff file found\n")
        return 1
    target = next((p for p in phases if p.number == args.number), None)
    if target is None:
        sys.stderr.write(f"kaizen-roadmap: no Phase {args.number} in handoff\n")
        return 1
    print(render_phase(target))
    return 0

def cmd_path(args) -> int:
    p = resolve_handoff_path()
    if p is None:
        sys.stderr.write("kaizen-roadmap: no handoff file found\n")
        return 1
    print(p)
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kaizen-roadmap",
        description="Parse phase-progress tables from a kaizen handoff "
                    "and render a dashboard.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("progress", help="dashboard (default view)")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_progress)

    pn = sub.add_parser("next", help="next pending item only")
    pn.add_argument("--json", action="store_true")
    pn.set_defaults(func=cmd_next)

    pl = sub.add_parser("phases", help="list phase names + counts")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_phases)

    ps = sub.add_parser("phase", help="detail one phase")
    ps.add_argument("number", type=int)
    ps.set_defaults(func=cmd_phase)

    px = sub.add_parser("path", help="resolved handoff path")
    px.set_defaults(func=cmd_path)

    args = parser.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
