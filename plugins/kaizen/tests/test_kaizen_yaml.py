"""TDD RED for kaizen-yaml — YAML aggregator over rubrics/schemas/intents/handoffs.

Aggregator scope (read-only):
- skills/<feature>/domain/*.yaml (rubrics, configs, rule catalogs)
- schemas/<routine>/schema.yaml (workflow routines)
- ~/.claude/handoff/<session>/*.yaml (handoff documents)

Subcommands: list / show / lint / path
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/io/kaizen_yaml.py"


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
        self.assertTrue((_KZ_DIR / "bin" / "kaizen-yaml").is_file())


class YamlBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.plugin_root = self.tmp / "plugin"
        self.plugin_root.mkdir()
        self._orig = os.environ.get("KAIZEN_PLUGIN_ROOT")
        os.environ["KAIZEN_PLUGIN_ROOT"] = str(self.plugin_root)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_PLUGIN_ROOT", None)
        else:
            os.environ["KAIZEN_PLUGIN_ROOT"] = self._orig

    def _seed(self, rel: str, body: str) -> Path:
        p = self.plugin_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p


class TestList(YamlBase):
    def test_list_empty_when_no_yamls(self):
        import json
        r = _run("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["count"], 0)

    def test_list_discovers_seeded_yamls(self):
        import json
        self._seed("schemas/foo/foo-rubric.yaml", "version: 1\nrules: []\n")
        self._seed("schemas/bar/config.yaml", "version: 1\nkey: value\n")
        self._seed("schemas/audit/schema.yaml", "name: audit\nversion: 1\nartifacts: []\n")
        r = _run("list", "--json")
        data = json.loads(r.stdout)
        self.assertGreaterEqual(data["count"], 3)
        names = {f["name"] for f in data["files"]}
        self.assertIn("foo-rubric.yaml", names)
        self.assertIn("config.yaml", names)
        self.assertIn("schema.yaml", names)

    def test_list_carries_category(self):
        import json
        self._seed("schemas/foo/foo-rubric.yaml", "version: 1\n")
        self._seed("schemas/audit/schema.yaml", "name: audit\n")
        r = _run("list", "--json")
        data = json.loads(r.stdout)
        cats = {f["category"] for f in data["files"]}
        self.assertIn("rubric", cats)  # *-rubric.yaml
        self.assertIn("routine", cats)  # schemas/<x>/schema.yaml


class TestShow(YamlBase):
    def test_show_emits_parsed_yaml(self):
        import json
        self._seed("schemas/foo/test.yaml", "version: 1\nkey: hello\n")
        r = _run("show", "test.yaml")
        self.assertEqual(r.returncode, 0)
        # Output should be parseable YAML or JSON (we emit JSON)
        data = json.loads(r.stdout)
        self.assertEqual(data["key"], "hello")
        self.assertEqual(data["version"], 1)

    def test_show_missing_returns_1(self):
        r = _run("show", "vanished.yaml")
        self.assertEqual(r.returncode, 1)


class TestLint(YamlBase):
    def test_lint_passes_on_valid_yaml(self):
        self._seed("schemas/foo/ok.yaml", "version: 1\nkey: value\n")
        r = _run("lint")
        self.assertEqual(r.returncode, 0)
        self.assertIn("ok.yaml", r.stdout)

    def test_lint_reports_broken_yaml(self):
        self._seed("schemas/foo/bad.yaml", "  invalid: : :")
        r = _run("lint")
        # Exit 1 on any broken file
        self.assertEqual(r.returncode, 1)
        self.assertIn("bad.yaml", r.stdout + r.stderr)


class TestPath(YamlBase):
    def test_path_prints_plugin_root(self):
        r = _run("path")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), str(self.plugin_root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
