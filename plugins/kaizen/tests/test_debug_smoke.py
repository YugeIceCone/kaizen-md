"""Tests for `kaizen-debug smoke` — exercise every bin's --help and
surface failures.

KISS scope - bin-only smoke for now (slash and MCP have their own
smoke surfaces: `kaizen-metrics smoke --kind mcp` covers MCPs;
slash commands are interactive). The bin surface is the gap.

Bins that need user input or run long are skipped via a deny-list
(install / publish / update / browser / loop / daemon etc.).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_DEBUG_PY = _KZ / "scripts" / "debug.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_DEBUG_PY), *args],
        capture_output=True, text=True, timeout=120,
        env={**os.environ},
    )


class TestSmokeSubcommand(unittest.TestCase):
    """`debug.py smoke` walks bin/kaizen-* and reports failures."""

    def test_smoke_kind_bin_returns_envelope(self):
        """Default `smoke --json` returns {passed, failed, skipped,
        results: [{name, rc, ok, error?}]}."""
        r = _run("smoke", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        # Envelope shape
        self.assertIn("passed", out)
        self.assertIn("failed", out)
        self.assertIn("skipped", out)
        self.assertIn("results", out)
        # Each result has name + rc + ok
        self.assertGreater(len(out["results"]), 0)
        for r in out["results"][:3]:
            self.assertIn("name", r)
            self.assertIn("ok", r)

    def test_smoke_human_output_shows_counts(self):
        r = _run("smoke")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Output contains the rollup line
        self.assertIn("passed", r.stdout.lower())
        self.assertIn("failed", r.stdout.lower())

    def test_smoke_failures_have_error_text(self):
        """If any bin fails, its result entry must carry stderr."""
        r = _run("smoke", "--json")
        out = json.loads(r.stdout)
        for res in out["results"]:
            if not res["ok"]:
                self.assertIn("error", res,
                               f"failure for {res['name']} has no error text")
                self.assertTrue(res["error"],
                                f"failure for {res['name']} has empty error")


if __name__ == "__main__":
    unittest.main()
