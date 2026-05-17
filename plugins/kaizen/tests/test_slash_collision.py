"""TDD #3 — slash-prefix collision detector.

When 2+ /kaizen:<slash> commands share a >=4-char prefix, surface them
as a routing-ambiguity finding (warn-severity, advisory). The lint
catches tab-completion conflicts before they ship.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "plugins/kaizen/skills/workflow/scripts/slash_collision.py"


def _load():
    spec = importlib.util.spec_from_file_location("slash_collision", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["slash_collision"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestCollisionDetection(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_no_collisions_returns_empty(self):
        names = ["audit", "brain", "loop", "setup", "trace"]
        self.assertEqual(self.mod.find_collisions(names), [])

    def test_two_4char_prefix_collision(self):
        names = ["gate", "gatekeeper"]
        out = self.mod.find_collisions(names)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["prefix"], "gate")
        self.assertEqual(sorted(out[0]["members"]), ["gate", "gatekeeper"])

    def test_three_way_collision_groups(self):
        names = ["trace", "trace-search", "trace-proxy"]
        out = self.mod.find_collisions(names)
        # All three share "trac"+ prefix — exactly one collision group
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["members"]), 3)

    def test_threshold_skips_names_shorter_than_min(self):
        """A 3-char name (`use`) can't collide at threshold=4 — too short
        to even reach the prefix length. Skipped, not flagged."""
        names = ["use", "userprompt"]
        self.assertEqual(self.mod.find_collisions(names, min_prefix_len=4), [])

    def test_threshold_configurable_via_arg(self):
        """At threshold=3 `use` + `userprompt` DO collide (share `use`)."""
        names = ["use", "userprompt"]
        out = self.mod.find_collisions(names, min_prefix_len=3)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["prefix"], "use")

    def test_mode_models_collide_at_default_threshold(self):
        """Real historical case — `mode` + `models` share 4-char prefix
        `mode` (since `models[:4] == 'mode'`). This is exactly the
        collision the user flagged before mode was folded into workflow.
        Detector must catch it at the default threshold."""
        out = self.mod.find_collisions(["mode", "models"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["prefix"], "mode")

    def test_singletons_ignored(self):
        """A 4-char prefix shared by only ONE name is not a collision."""
        names = ["audit"]
        self.assertEqual(self.mod.find_collisions(names), [])


class TestCommandsDirScan(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_scan_dir_returns_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "gate.md").write_text("---\nname: gate\n---\n")
            (d / "gatekeeper.md").write_text("---\nname: gatekeeper\n---\n")
            (d / "brain.md").write_text("---\nname: brain\n---\n")
            out = self.mod.scan_commands_dir(d)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["prefix"], "gate")

    def test_scan_dir_ignores_non_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "gate.md").write_text("")
            (d / "gatekeeper.md").write_text("")
            (d / "README.txt").write_text("")
            out = self.mod.scan_commands_dir(d)
            self.assertEqual(sorted(out[0]["members"]),
                              sorted(["gate", "gatekeeper"]))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_cli_returns_0_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "audit.md").write_text("")
            (d / "brain.md").write_text("")
            rc = self.mod.main(["check", "--dir", str(d)])
            self.assertEqual(rc, 0)

    def test_cli_returns_1_when_collisions_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "gate.md").write_text("")
            (d / "gatekeeper.md").write_text("")
            rc = self.mod.main(["check", "--dir", str(d)])
            self.assertEqual(rc, 1)

    def test_cli_json_emits_structured_output(self):
        import io
        import json
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "gate.md").write_text("")
            (d / "gatekeeper.md").write_text("")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.mod.main(["check", "--dir", str(d), "--json"])
            data = json.loads(buf.getvalue())
            self.assertIn("collisions", data)
            self.assertEqual(data["collisions"][0]["prefix"], "gate")


if __name__ == "__main__":
    unittest.main()
