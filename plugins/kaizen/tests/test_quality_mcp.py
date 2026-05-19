"""TDD — quality_mcp.py bundles 5 quality axes as MCP tools.

The gatekeeper aggregator currently sums them into one verdict; this
server exposes each axis as a discrete query so agents can drill into
the dimension they care about without re-running the whole gate.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/mcp/quality_mcp.py"


def _load():
    spec = importlib.util.spec_from_file_location("quality_mcp_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["quality_mcp_test"] = mod
    scripts_dir = str(_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec.loader.exec_module(mod)
    return mod


class TestQualityMcpServer(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_module_exports_mcp_instance(self):
        self.assertTrue(hasattr(self.mod, "mcp"))
        self.assertEqual(self.mod.mcp.name, "quality")

    def test_five_axis_tools_registered(self):
        """One tool per axis: frontmatter / coverage / name-quality /
        schema-coverage / slash-collision."""
        tools = asyncio.run(self.mod.mcp._list_tools())
        names = {t.name for t in tools}
        for expected in (
            "frontmatter_gaps",
            "coverage_gaps",
            "name_quality_gaps",
            "schema_coverage_gaps",
            "slash_collisions",
        ):
            self.assertIn(expected, names,
                           f"missing tool {expected}; got {sorted(names)}")


class TestQualityAxisShapes(unittest.TestCase):
    """Each axis returns a dict with `count` + `findings` (list)."""

    def setUp(self):
        self.mod = _load()

    def test_frontmatter_gaps_returns_count_and_findings(self):
        r = self.mod.frontmatter_gaps()
        self.assertIsInstance(r, dict)
        self.assertIn("count", r)
        self.assertIn("findings", r)
        self.assertIsInstance(r["findings"], list)

    def test_slash_collisions_returns_count_and_findings(self):
        r = self.mod.slash_collisions()
        self.assertIsInstance(r, dict)
        self.assertIn("count", r)
        self.assertIsInstance(r["findings"], list)

    def test_coverage_gaps_returns_count_and_findings(self):
        r = self.mod.coverage_gaps()
        self.assertIsInstance(r, dict)
        self.assertIn("count", r)
        self.assertIn("findings", r)

    def test_name_quality_gaps_returns_count_and_findings(self):
        r = self.mod.name_quality_gaps()
        self.assertIsInstance(r, dict)
        self.assertIn("count", r)
        self.assertIn("findings", r)

    def test_schema_coverage_gaps_returns_count_and_findings(self):
        r = self.mod.schema_coverage_gaps()
        self.assertIsInstance(r, dict)
        self.assertIn("count", r)
        self.assertIn("findings", r)


class TestSlashCollisionsRealSurface(unittest.TestCase):
    """Live-data check — the slash_collisions tool surfaces prefix-overlap
    families in commands/. Post consolidate-2 D1-D7 the menu collapsed
    from 56 → 9 (8 roots + audit:axis) so most historical families
    (back* / self* / stat* / trac*) no longer overlap. The tool must
    still return a well-formed envelope; absence of findings is now
    the expected steady state."""

    def setUp(self):
        self.mod = _load()

    def test_real_collisions_envelope_well_formed(self):
        r = self.mod.slash_collisions()
        self.assertIsInstance(r, dict)
        self.assertIn("count", r)
        self.assertIn("findings", r)
        self.assertEqual(r["count"], len(r["findings"]))
        for f in r["findings"]:
            self.assertIn("prefix", f)


if __name__ == "__main__":
    unittest.main()
