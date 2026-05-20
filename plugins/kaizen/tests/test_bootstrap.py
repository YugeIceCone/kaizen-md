"""Tests for bootstrap.sh — pre-warms the plugin's uv-managed Python surface."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
BOOTSTRAP = PLUGIN / "scripts" / "install" / "bootstrap.sh"


class TestBootstrap(unittest.TestCase):
    def test_bootstrap_script_exists_and_is_bash(self):
        self.assertTrue(BOOTSTRAP.is_file())
        r = subprocess.run(["bash", "-n", str(BOOTSTRAP)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_check_mode_passes_when_uv_present(self):
        # --check only verifies uv is installed; no pre-warm, no network.
        r = subprocess.run(["bash", str(BOOTSTRAP), "--check"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0,
                         f"uv should be present in the test env\n{r.stderr}")

    def test_list_mode_includes_daemon_and_loc_index(self):
        # --list enumerates the PEP-723 `uv run --script` files without
        # running anything — daemon.py joined that set (it now has a
        # `# /// script` block), loc_index.py was always in it.
        r = subprocess.run(["bash", str(BOOTSTRAP), "--list"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("daemon.py", r.stdout)
        self.assertIn("loc_index.py", r.stdout)


if __name__ == "__main__":
    unittest.main()
