"""Tests for the plugin_index_root() SSOT (_paths.py + _paths.sh)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import _paths  # noqa: E402

class TestPluginIndexRootPy(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("KAIZEN_PLUGIN_INDEX_ROOT", "KAIZEN_MARKETPLACE")}

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["KAIZEN_PLUGIN_INDEX_ROOT"] = td
            self.assertEqual(_paths.plugin_index_root(), Path(td).resolve())

    def test_falls_back_to_marketplace_realpath(self):
        os.environ.pop("KAIZEN_PLUGIN_INDEX_ROOT", None)
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real-market"
            real.mkdir()
            link = Path(td) / "link-market"
            link.symlink_to(real)
            os.environ["KAIZEN_MARKETPLACE"] = str(link)
            # symlink must be resolved to the real path
            self.assertEqual(_paths.plugin_index_root(), real.resolve())

class TestPluginIndexRootSh(unittest.TestCase):
    def test_sh_mirrors_py(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, KAIZEN_PLUGIN_INDEX_ROOT=td)
            out = subprocess.run(
                ["bash", "-c",
                 f'source "{SCRIPTS}/_paths.sh" && kaizen_plugin_index_root'],
                env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.strip(), str(Path(td).resolve()))

if __name__ == "__main__":
    unittest.main()
