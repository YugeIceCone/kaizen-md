"""unused-env (idea #4): env-vars defined in .kaizen.toml or .env but never read."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import unused_env  # noqa: E402

class TestUnusedEnv(unittest.TestCase):
    def test_unused_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".kaizen.toml").write_text(
                'unused_env_var = "FOO_UNUSED_KEY"\nallow_deletion_env = "KAIZEN_ALLOW_DELETE"\n')
            (root / "scripts/util").mkdir(parents=True)
            (root / "scripts/util/x.py").write_text(
                'import os\nos.environ.get("KAIZEN_ALLOW_DELETE")\n')
            rep = unused_env.scan(repo_root=root)
            keys = {g["env_var"] for g in rep["gaps"]}
            self.assertIn("FOO_UNUSED_KEY", keys)
            self.assertNotIn("KAIZEN_ALLOW_DELETE", keys)

if __name__ == "__main__":
    unittest.main()
