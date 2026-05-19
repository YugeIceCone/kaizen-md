"""Tests for `_smart_since` — picks the best `--since` cutoff for tree/queries.

Per Task #40 brainstorm — item #2 (impact 4 × effort 1 = score 16).
Threads parent_handoff into the default cutoff so `handoff tree`
catches exactly the commits made AFTER the resumed-from session
ended, not a broad day-bucket guess.

Priority:
  1. parent_handoff's handoff_generated_at (most precise — exact UTC ts)
  2. current handoff's `date:` field (broader — day-bucket)
  3. None (caller picks default; usually "1 week ago")
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HANDOFF = _KZ / "skills/workflow/scripts/handoff.py"

sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/rules"))
import handoff as _h  # noqa: E402


_PARENT_YAML = """---
session: test
date: 2026-05-17
status: complete
---

session_meta:
  handoff_generated_at: '2026-05-17T20:02:59Z'
  cc_session_uuid: 'parent-sid'

goal: 'parent goal'
"""


def _child_yaml_with_parent(parent_path: str) -> str:
    return f"""---
session: test
date: 2026-05-18
status: partial
---

session_meta:
  cc_session_uuid: 'child-sid'
  handoff_generated_at: '2026-05-18T18:30:00Z'
  parent_handoff: '{parent_path}'

goal: 'child goal'

done_this_session:
  - task: 'a thing'
    files: ['a.py']
"""


_ORPHAN_YAML = """---
session: test
date: 2026-05-18
status: partial
---

session_meta:
  cc_session_uuid: 'orphan-sid'
  handoff_generated_at: '2026-05-18T18:30:00Z'

goal: 'no parent'
"""


class TestSmartSince(unittest.TestCase):
    def test_uses_parent_handoff_generated_at_when_parent_exists(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td) / "parent.yaml"
            parent.write_text(_PARENT_YAML, encoding="utf-8")
            child_text = _child_yaml_with_parent(str(parent))
            self.assertEqual(_h._smart_since(child_text),
                              "2026-05-17T20:02:59Z")

    def test_falls_back_to_date_when_no_parent(self):
        # No parent_handoff in session_meta → use current `date:`
        self.assertEqual(_h._smart_since(_ORPHAN_YAML), "2026-05-18")

    def test_returns_none_when_neither_present(self):
        text = """---
session: test
status: partial
---

session_meta:
  cc_session_uuid: 'x'

goal: 'nothing'
"""
        self.assertIsNone(_h._smart_since(text))

    def test_missing_parent_file_falls_back_to_date(self):
        # parent_handoff points at a nonexistent path → graceful fallback
        text = _child_yaml_with_parent("/tmp/does-not-exist-42.yaml")
        # Should not crash; falls back to current date
        self.assertEqual(_h._smart_since(text), "2026-05-18")

    def test_parent_without_handoff_generated_at_falls_back(self):
        # Parent exists but its session_meta lacks handoff_generated_at
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td) / "p.yaml"
            parent.write_text(
                "---\nsession: test\ndate: 2026-05-17\n---\n\nsession_meta:\n  cc_session_uuid: 'x'\n",
                encoding="utf-8")
            child = _child_yaml_with_parent(str(parent))
            # parent has no handoff_generated_at → use child's date
            self.assertEqual(_h._smart_since(child), "2026-05-18")


# ─── tree CLI uses smart since when --since omitted ─────────────────────

def _git_init_with_commit(repo: Path) -> str:
    for cmd in (["git", "init", "-q", "-b", "main"],
                 ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=str(repo), check=True, capture_output=True)
    (repo / "a.py").write_text("# a\n")
    subprocess.run(["git", "add", "a.py"], cwd=str(repo), check=True,
                    capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"],
                    cwd=str(repo), check=True, capture_output=True)
    r = subprocess.run(["git", "log", "-1", "--format=%h"],
                        cwd=str(repo), capture_output=True, text=True)
    return r.stdout.strip()


class TestTreeUsesSmartSince(unittest.TestCase):
    def test_tree_default_since_uses_parent_timestamp_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _git_init_with_commit(repo)
            parent = repo / "parent.yaml"
            parent.write_text(_PARENT_YAML, encoding="utf-8")
            child = repo / "child.yaml"
            child.write_text(_child_yaml_with_parent(str(parent)),
                              encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "GIT_DIR"}
            r = subprocess.run(
                [sys.executable, str(_HANDOFF), "tree", "--file", str(child)],
                capture_output=True, text=True, timeout=15,
                env=env, cwd=str(repo),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            import json
            data = json.loads(r.stdout)
            # since should be parent's handoff_generated_at (passed through
            # _normalize_since, but this isn't a bare YYYY-MM-DD so untouched)
            self.assertEqual(data["since"], "2026-05-17T20:02:59Z")


if __name__ == "__main__":
    unittest.main()
