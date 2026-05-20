"""kaizen-brain block-level addressing — pure-function core.

Markdown headings (`#`, `##`, `###`) define addressable blocks via
heading-path. One CLI call retrieves exactly the block you need;
one more edits it in place. Zero whole-file reads.

Block model:
  - A block = lines from a heading line through the next sibling-or-
    shallower heading (exclusive).
  - The block path is `/`-joined heading text, e.g.
    `Document/Top Beliefs`.
  - A file with no headings yields a single synthetic block at path ""
    spanning lines [0, len(lines)).

Design contract (per pref-prcdr-contract-declared):
  PROGRAMMABLE  — every public callable is pure
  REPRODUCIBLE  — same text → same blocks (deterministic ordering)
  CONSISTENT    — every block dict has {path, level, start, end}
  DETERMINISTIC — no clock, no env, no I/O
  REUSABLE      — works for any Markdown file with headings
"""
from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

def parse_blocks(text: str) -> list[dict]:
    """Return list of blocks, each {path, level, start, end}.

    `start` is the heading line's 0-based index; `end` is the line
    AFTER the last line in the block (exclusive). Slicing
    `lines[start:end]` yields the block content (heading included).

    A file with no headings returns a single synthetic block with
    path="" covering the whole file.
    """
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2)))
    if not headings:
        return [{"path": "", "level": 0, "start": 0, "end": len(lines)}]

    blocks: list[dict] = []
    stack: list[tuple[int, str]] = []
    for idx, (lineno, level, title) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        path_parts = [t for _, t in stack] + [title]
        path = "/".join(path_parts)
        end = len(lines)
        for j in range(idx + 1, len(headings)):
            other_line, other_level, _ = headings[j]
            if other_level <= level:
                end = other_line
                break
        blocks.append({"path": path, "level": level,
                        "start": lineno, "end": end})
        stack.append((level, title))
    return blocks

def _find_block(blocks: list[dict], block_ref: str) -> dict | None:
    """Resolve a block by full path OR trailing segment."""
    for b in blocks:
        if b["path"] == block_ref:
            return b
    matches = [b for b in blocks if b["path"].endswith("/" + block_ref)]
    if len(matches) == 1:
        return matches[0]
    return None

def extract_block(text: str, block_ref: str) -> str | None:
    """Return the block's body text (heading included). None if missing."""
    blocks = parse_blocks(text)
    b = _find_block(blocks, block_ref)
    if b is None:
        return None
    lines = text.splitlines()
    return "\n".join(lines[b["start"]:b["end"]])

def replace_block(text: str, block_ref: str, new_body: str) -> str:
    """Replace the named block's lines with `new_body`. Raises KeyError if missing."""
    blocks = parse_blocks(text)
    b = _find_block(blocks, block_ref)
    if b is None:
        raise KeyError(f"block not found: {block_ref!r}")
    lines = text.splitlines()
    new_lines = new_body.splitlines()
    out_lines = lines[:b["start"]] + new_lines + lines[b["end"]:]
    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")

def append_to_list_block(text: str, block_ref: str,
                          new_item_line: str) -> str:
    """Append a list-item line at the end of the named block's content.
    Caller provides the leading marker (-, 1., etc.).
    """
    blocks = parse_blocks(text)
    b = _find_block(blocks, block_ref)
    if b is None:
        raise KeyError(f"block not found: {block_ref!r}")
    lines = text.splitlines()
    end = b["end"]
    insert_at = end
    for i in range(end - 1, b["start"], -1):
        if lines[i].strip():
            insert_at = i + 1
            break
    new_lines = lines[:insert_at] + [new_item_line] + lines[insert_at:]
    return "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")

__all__ = ["parse_blocks", "extract_block",
            "replace_block", "append_to_list_block"]
