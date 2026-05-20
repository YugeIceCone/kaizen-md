"""axis_runner_mcp — FastMCP wrapper for the axis runner (#161 C5).

Verifies the module exposes a FastMCP instance with the canonical
three tools (`list_axes`, `run_axis`, `report`) and that smoke-calling
them returns dict envelopes.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/mcp/axis_runner_mcp.py"


def _load():
    spec = importlib.util.spec_from_file_location("axis_runner_mcp_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["axis_runner_mcp_test"] = mod
    scripts_dir = str(_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    legacy = str(_KZ_DIR / "skills/workflow/scripts")
    if legacy not in sys.path:
        sys.path.insert(0, legacy)
    spec.loader.exec_module(mod)
    return mod


class TestAxisRunnerMcp(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_module_exports_mcp_instance(self):
        self.assertTrue(hasattr(self.mod, "mcp"))
        self.assertEqual(self.mod.mcp.name, "kaizen-axis-runner")

    def test_tools_registered(self):
        tools = asyncio.run(self.mod.mcp._list_tools())
        names = {t.name for t in tools}
        for expected in ("list_axes", "run_axis", "report"):
            self.assertIn(
                expected, names,
                f"missing {expected}; got {sorted(names)}",
            )

    def test_list_axes_returns_envelope(self):
        envelope = asyncio.run(self.mod.list_axes())
        self.assertIsInstance(envelope, dict)
        # Either a clean envelope OR an error dict — both valid
        # Unconditional: subprocess success is a precondition. A missing
        # "data" key signals a real failure (conditional asserts hid it).
        self.assertIn("data", envelope)
        self.assertIn("axes", envelope["data"])

    def test_run_axis_returns_envelope_for_reference_demo(self):
        # axis stem must match the yaml filename — reference_demo.yaml,
        # NOT "reference-demo" (the conditional `if "data" in envelope`
        # hid this hyphen-vs-underscore bug before BK-060 tightened the
        # asserts).
        envelope = asyncio.run(self.mod.run_axis("reference_demo"))
        self.assertIsInstance(envelope, dict)
        self.assertIn("data", envelope)
        self.assertEqual(envelope["data"].get("axis"), "reference-demo")


if __name__ == "__main__":
    unittest.main()
