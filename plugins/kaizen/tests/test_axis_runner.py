"""axis-runner (#161): declarative axis YAML → loader → grep-dispatcher → envelope.

C1 RED: test_load_and_run_grep_axis writes an axis.yaml + fixture files
into a sandboxed tmpdir, calls `run_axis(yaml_path, root=tmp)`, and
asserts the canonical envelope shape (`kaizen` meta + `data.findings`
+ `verdict`).
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/io"))


class TestAxisRunner(unittest.TestCase):
    def test_load_and_run_grep_axis(self):
        import axis_runner  # noqa: WPS433 — lazy import; module must exist

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            # Fixture: one file with a trailing-ws line + one clean file
            (root / "docs" / "bad.md").write_text("clean line\ntrailing  \n")
            (root / "docs" / "ok.md").write_text("nothing here\n")

            axis_yaml = root / "trailing-ws.yaml"
            axis_yaml.write_text(textwrap.dedent("""
                name: trailing-ws
                scan_spec:
                  type: grep
                  pattern: " +$"
                  glob: "docs/*.md"
                verdict_rule:
                  green_max: 0
                  yellow_max: 10
            """).strip() + "\n")

            envelope = axis_runner.run_axis(axis_yaml, root=root)

            # Envelope shape
            self.assertIn("kaizen", envelope)
            self.assertEqual(envelope["kaizen"]["tool"], "kaizen-axis-runner")
            self.assertIn("data", envelope)
            self.assertIn("findings", envelope["data"])
            self.assertIn("verdict", envelope)

            findings = envelope["data"]["findings"]
            self.assertGreaterEqual(len(findings), 1)
            # At least one finding points at bad.md
            paths = [f["path"] for f in findings]
            self.assertTrue(any("bad.md" in p for p in paths))
            # Verdict yellow (1 finding within yellow_max=10)
            self.assertEqual(envelope["verdict"], "yellow")

    def test_load_returns_axis_spec_with_name(self):
        import axis_runner  # noqa

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            axis_yaml = root / "demo.yaml"
            axis_yaml.write_text(textwrap.dedent("""
                name: demo
                scan_spec:
                  type: grep
                  pattern: "TODO"
                  glob: "**/*.py"
                verdict_rule:
                  green_max: 0
                  yellow_max: 5
            """).strip() + "\n")

            spec = axis_runner.load(axis_yaml)
            self.assertEqual(spec["name"], "demo")
            self.assertEqual(spec["scan_spec"]["type"], "grep")


if __name__ == "__main__":
    unittest.main()
