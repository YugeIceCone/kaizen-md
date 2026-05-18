"""Tests for kaizen-plugin-docs — utility surface tracker for plugins/kaizen/.

Symmetry with kaizen-bundle but for DURABLE docs (no bundle/session
concept; no mutation). Walks the canonical doc surfaces of the kaizen
plugin: skills (SKILL.md), skill references, commands, agents, root
docs, and domain configs. Reports counts + per-file metadata + content-
hash dupes.

  kaizen-plugin-docs scan [--json]
  kaizen-plugin-docs list [--kind <kind>] [--json]

Kinds (kind classifier — pure function over a path):
  skill          plugins/kaizen/skills/<name>/SKILL.md
  reference      plugins/kaizen/skills/<name>/references/*.md
  command        plugins/kaizen/commands/*.md
  agent          plugins/kaizen/agents/*.md
  root           plugins/kaizen/{README,CLAUDE,CHANGELOG,ATTRIBUTIONS,
                  CONTRIBUTING}.md
  domain         plugins/kaizen/skills/<name>/domain/**.{yaml,json}
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
_DOCS_PY = _KZ_DIR / "skills/workflow/scripts/plugin_docs.py"


class _DocsBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Build a tiny fake plugin root
        self.root = self.tmp / "plugin-root"
        (self.root / "skills/foo").mkdir(parents=True)
        (self.root / "skills/foo/SKILL.md").write_text("# foo skill\n")
        (self.root / "skills/foo/references").mkdir()
        (self.root / "skills/foo/references/api.md").write_text("# api\n")
        (self.root / "skills/foo/domain").mkdir()
        (self.root / "skills/foo/domain/rules.yaml").write_text("v: 1\n")
        (self.root / "skills/bar").mkdir()
        (self.root / "skills/bar/SKILL.md").write_text("# bar skill\n")
        (self.root / "commands").mkdir()
        (self.root / "commands/foo.md").write_text("# /kaizen:foo\n")
        (self.root / "commands/bar.md").write_text("# /kaizen:bar\n")
        (self.root / "agents").mkdir()
        (self.root / "agents/sample-agent.md").write_text("# agent\n")
        (self.root / "README.md").write_text("# readme\n")
        (self.root / "CLAUDE.md").write_text("# claude\n")
        # env override
        self._orig = os.environ.get("KAIZEN_PLUGIN_ROOT")
        os.environ["KAIZEN_PLUGIN_ROOT"] = str(self.root)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_PLUGIN_ROOT", None)
        else:
            os.environ["KAIZEN_PLUGIN_ROOT"] = self._orig

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DOCS_PY), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )


class TestKindClassifier:
    def test_pure_fn(self):
        import sys as _sys
        _sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        from plugin_docs import classify_kind
        assert classify_kind(Path("plugins/kaizen/skills/foo/SKILL.md")) == "skill"
        assert classify_kind(Path("plugins/kaizen/skills/foo/references/api.md")) == "reference"
        assert classify_kind(Path("plugins/kaizen/skills/foo/domain/x.yaml")) == "domain"
        assert classify_kind(Path("plugins/kaizen/skills/foo/domain/schemas/x.json")) == "domain"
        assert classify_kind(Path("plugins/kaizen/commands/foo.md")) == "command"
        assert classify_kind(Path("plugins/kaizen/agents/sample-agent.md")) == "agent"
        assert classify_kind(Path("plugins/kaizen/README.md")) == "root"
        assert classify_kind(Path("plugins/kaizen/CLAUDE.md")) == "root"
        assert classify_kind(Path("plugins/kaizen/skills/foo/scripts/x.py")) is None


class TestScanCounts(_DocsBase):
    def test_counts_by_kind(self):
        r = self._run("scan", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        c = data["counts"]
        self.assertEqual(c["skill"], 2)
        self.assertEqual(c["reference"], 1)
        self.assertEqual(c["command"], 2)
        self.assertEqual(c["agent"], 1)
        self.assertEqual(c["root"], 2)
        self.assertEqual(c["domain"], 1)

    def test_total_matches_sum_of_kinds(self):
        r = self._run("scan", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["total"], sum(data["counts"].values()))


class TestScanDupes(_DocsBase):
    def test_identical_content_flagged(self):
        # Create a 3rd skill with content IDENTICAL to foo's SKILL.md
        (self.root / "skills/baz").mkdir()
        (self.root / "skills/baz/SKILL.md").write_text("# foo skill\n")
        r = self._run("scan", "--json")
        data = json.loads(r.stdout)
        # At least one dupe pair
        self.assertGreaterEqual(len(data["dupes"]), 1)
        # Pair includes both files
        names = set()
        for d in data["dupes"]:
            names.update(d["paths"])
        self.assertIn("skills/foo/SKILL.md", " ".join(names))


class TestList(_DocsBase):
    def test_list_all_default(self):
        r = self._run("list", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2 + 1 + 2 + 1 + 2 + 1)
        # Each entry carries path + kind + size + sha256
        for entry in data:
            for k in ("path", "kind", "size", "sha256"):
                self.assertIn(k, entry)

    def test_list_filter_by_kind(self):
        r = self._run("list", "--kind", "skill", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)
        for entry in data:
            self.assertEqual(entry["kind"], "skill")

    def test_list_human_readable_default(self):
        r = self._run("list", "--kind", "skill")
        self.assertEqual(r.returncode, 0)
        # Each skill name appears in output
        self.assertIn("SKILL.md", r.stdout)


class TestGracefulMissingRoot(unittest.TestCase):
    def test_missing_root_zero_counts(self):
        env = os.environ.copy()
        env["KAIZEN_PLUGIN_ROOT"] = "/nope/missing-root"
        r = subprocess.run(
            [sys.executable, str(_DOCS_PY), "scan", "--json"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["total"], 0)


if __name__ == "__main__":
    unittest.main()
