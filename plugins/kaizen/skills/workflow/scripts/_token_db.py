#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "tree-sitter>=0.23",
#   "tree-sitter-rust>=0.23",
#   "tree-sitter-python>=0.23",
# ]
# ///
"""Token-map SQLite layer for kaizen-tokens MCP server.

Phase 1 (T1) — skeleton only. T2 expands schema + CRUD + rename
detection + IMMEDIATE-tx version bumps per spec
`docs/2026-05-18-positional-token-schema-design.md`.

Private helper (underscore-prefixed) — exempt from
`bin-wrapper-per-cli` iron-law (see `_iron_laws.py:196`).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["TokenDB"]


class TokenDB:
    """SQLite-backed token map (skeleton).

    T2 expands with init_schema, upsert_file, upsert_slots, etc.
    Per spec V25: write paths wrap in `with self.conn:` for
    IMMEDIATE transactions so readers see fully old or fully new
    state — never torn.
    """

    def __init__(self, path: Path):
        self.path = path


if __name__ == "__main__":
    # Phase 1 (T1): probe — confirms PEP-723 venv has the 3 deps.
    import tree_sitter        # noqa: F401
    import tree_sitter_rust   # noqa: F401
    import tree_sitter_python # noqa: F401
    print("_token_db.py: deps OK")
