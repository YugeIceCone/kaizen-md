"""hook-coverage (idea #35): every hooks/claude/*.sh wired in hooks.json."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import hook_coverage  # noqa: E402

class TestHookCoverage(unittest.TestCase):
    def test_scan_returns_expected_shape(self):
        rep = hook_coverage.scan(
            hooks_dir=_KZ / "hooks/claude",
            hooks_json=_KZ / "hooks/hooks.json",
        )
        for k in ("scripts_on_disk", "wired_entries", "orphans",
                   "missing", "gaps_total"):
            self.assertIn(k, rep)
        self.assertGreater(rep["scripts_on_disk"], 0,
            "should find ≥1 hook script on disk")

    def test_orphans_and_missing_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            hd = Path(td) / "hooks"
            hd.mkdir()
            (hd / "wired-and-present.sh").write_text("#!/bin/bash\n")
            (hd / "orphan.sh").write_text("#!/bin/bash\n")
            hj = Path(td) / "hooks.json"
            hj.write_text(json.dumps({
                "hooks": {
                    "SessionStart": [{"hooks": [
                        {"type": "command",
                         "command": "bash ${ROOT}/hooks/claude/wired-and-present.sh"},
                        {"type": "command",
                         "command": "bash ${ROOT}/hooks/claude/missing-file.sh"},
                    ]}],
                }
            }))
            rep = hook_coverage.scan(hooks_dir=hd, hooks_json=hj)
            orphan_names = {o["script"] for o in rep["orphans"]}
            missing_names = {m["script"] for m in rep["missing"]}
            self.assertIn("orphan.sh", orphan_names)
            self.assertIn("missing-file.sh", missing_names)
            self.assertNotIn("wired-and-present.sh", orphan_names)
            self.assertNotIn("wired-and-present.sh", missing_names)

if __name__ == "__main__":
    unittest.main()
