"""TDD RED for kaizen-state — JSON aggregator over all JSON state files.

Aggregator scope:
- backlog.json, state.json (workflow)
- session-mode.json
- mine-cursor.json (per-project gold)
- token-bloat-findings.json
- inbox/*.json
- CC auto-memory feedback markers (read-only pointers)

Read-only by design: sources stay in place; aggregator emits a unified
inventory view. Subcommands: list / show / dump / path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/state/state.py"


def _run(*args, env_extra=None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=10, env=env,
    )


class TestArtifact(unittest.TestCase):
    def test_script_present(self):
        self.assertTrue(_SCRIPT.is_file())

    def test_script_parses(self):
        with open(_SCRIPT) as f:
            compile(f.read(), str(_SCRIPT), "exec")

    def test_bin_wrapper_present(self):
        self.assertTrue((_KZ_DIR / "bin" / "kaizen-state").is_file())


class StateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.kaizen_dir = self.tmp / ".kaizen"
        self.kaizen_dir.mkdir()
        self._orig_dir = os.environ.get("KAIZEN_DIR")
        os.environ["KAIZEN_DIR"] = str(self.kaizen_dir)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig_dir is None:
            os.environ.pop("KAIZEN_DIR", None)
        else:
            os.environ["KAIZEN_DIR"] = self._orig_dir

    def _seed(self, rel: str, body) -> Path:
        p = self.kaizen_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body) if not isinstance(body, str) else body,
                       encoding="utf-8")
        return p


class TestList(StateBase):
    def test_list_empty_when_no_files(self):
        r = _run("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["files"], [])

    def test_list_discovers_seeded_files(self):
        self._seed("workflow/backlog.json", {"items": []})
        self._seed("session-mode.json", {"mode": "workflow"})
        self._seed("gold/-test/mine-cursor.json", {"dxm": {}})
        r = _run("list", "--json")
        data = json.loads(r.stdout)
        self.assertGreaterEqual(data["count"], 3)
        names = {f["name"] for f in data["files"]}
        self.assertIn("backlog.json", names)
        self.assertIn("session-mode.json", names)
        self.assertIn("mine-cursor.json", names)

    def test_list_carries_metadata(self):
        self._seed("session-mode.json", {"mode": "loop"})
        r = _run("list", "--json")
        data = json.loads(r.stdout)
        f = next(f for f in data["files"] if f["name"] == "session-mode.json")
        self.assertIn("path", f)
        self.assertIn("size", f)
        self.assertGreater(f["size"], 0)
        self.assertIn("category", f)


class TestShow(StateBase):
    def test_show_emits_parsed_json(self):
        self._seed("session-mode.json", {"mode": "workflow", "bundles": []})
        r = _run("show", "session-mode.json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["mode"], "workflow")

    def test_show_missing_returns_1(self):
        r = _run("show", "vanished.json")
        self.assertEqual(r.returncode, 1)


class TestDump(StateBase):
    def test_dump_aggregates_all(self):
        """`dump` emits a single JSON blob with every seeded file's
        contents indexed by name."""
        self._seed("workflow/state.json", {"current": 0, "stages": ["a", "b"]})
        self._seed("session-mode.json", {"mode": "loop"})
        r = _run("dump")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIn("state.json", data)
        self.assertIn("session-mode.json", data)
        self.assertEqual(data["session-mode.json"]["mode"], "loop")

    def test_dump_skips_unparseable(self):
        """Malformed JSON shouldn't crash the aggregator."""
        self._seed("workflow/backlog.json", "{ invalid")
        r = _run("dump")
        self.assertEqual(r.returncode, 0)
        # Backlog wasn't included; aggregator survived
        data = json.loads(r.stdout)
        self.assertNotIn("backlog.json", data)


class TestPath(StateBase):
    def test_path_prints_kaizen_dir(self):
        r = _run("path")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), str(self.kaizen_dir))


if __name__ == "__main__":
    unittest.main(verbosity=2)
