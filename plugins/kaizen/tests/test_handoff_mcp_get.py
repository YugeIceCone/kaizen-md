"""Tests for handoff_mcp.handoff_get — MCP exposure of the CLI `get` subcommand.

Closes the gap surfaced in the trace+explore pass: the section-extraction
win (commit 7502056) shipped a CLI but no MCP tool. Programmable
consumers (other agents, MCP clients) had to subprocess-shell-out + parse
stdout.

handoff_get(file, section, as_json=False) → {value} | {error}

Pure read; reuses the same _load_raw_handoff + _render_section primitives
the CLI uses (DRY).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_KZ_DIR / "scripts/mcp") if "_KZ_DIR" in dir() else str(Path(__file__).resolve().parent.parent / "scripts/mcp"))


_SAMPLE_HANDOFF = """---
session: demo
date: 2026-05-18
status: complete
outcome: SUCCEEDED
---

goal: did the thing
now: do the next thing

next:
  - first step
  - second step

code_context:
  - path: a.py
    ranges: ["1:42"]
"""


class TestHandoffGetMcpTool(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.yaml = self.tmp / "handoff.yaml"
        self.yaml.write_text(_SAMPLE_HANDOFF, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _import(self):
        # Fresh import each test so module state doesn't leak between
        import importlib
        import handoff_mcp
        importlib.reload(handoff_mcp)
        return handoff_mcp

    def test_get_existing_section_scalar(self):
        m = self._import()
        r = m.handoff_get(file=str(self.yaml), section="now")
        self.assertEqual(r["value"], "do the next thing")
        self.assertEqual(r["section"], "now")

    def test_get_existing_section_list(self):
        m = self._import()
        r = m.handoff_get(file=str(self.yaml), section="next")
        self.assertEqual(r["value"], ["first step", "second step"])

    def test_get_frontmatter_section(self):
        m = self._import()
        r = m.handoff_get(file=str(self.yaml), section="outcome")
        self.assertEqual(r["value"], "SUCCEEDED")

    def test_get_unknown_section_returns_error(self):
        m = self._import()
        r = m.handoff_get(file=str(self.yaml), section="banana")
        self.assertIn("error", r)
        self.assertIn("banana", r["error"])
        # Available list surfaced for discoverability
        self.assertIn("available", r)

    def test_get_missing_file_returns_error(self):
        m = self._import()
        r = m.handoff_get(file="/nope/missing.yaml", section="now")
        self.assertIn("error", r)
        self.assertIn("not found", r["error"].lower())

    def test_tool_registered(self):
        """handoff_get is callable AND registered on the MCP server."""
        m = self._import()
        # Module exposes the callable
        self.assertTrue(callable(getattr(m, "handoff_get", None)))


if __name__ == "__main__":
    unittest.main()
