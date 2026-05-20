"""Reference demo axis (#161) — proves blueprint item-06 (one YAML
axis subsumes a Python axis). Loads `domain/axes/reference_demo.yaml`
via `axis_runner.run_axis()` and verifies the envelope is
well-formed against a synthetic fixture root."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/io"))

_REFERENCE_YAML = (
    _KZ / "schemas/workflow/axes/reference_demo.yaml"
)

class TestReferenceDemoAxis(unittest.TestCase):
    def test_reference_yaml_exists(self):
        self.assertTrue(
            _REFERENCE_YAML.exists(),
            f"missing reference axis: {_REFERENCE_YAML}",
        )

    def test_reference_axis_loads_and_runs_against_fixture(self):
        import axis_runner

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Fixture: 2 trailing-ws lines in dirty.md, none in clean.md
            (root / "dirty.md").write_text(
                "first line with trail  \n"
                "second OK line\n"
                "third with trail   \n"
            )
            (root / "clean.md").write_text("nothing here\n")

            envelope = axis_runner.run_axis(_REFERENCE_YAML, root=root)

            self.assertEqual(
                envelope["kaizen"]["tool"], "kaizen-axis-runner"
            )
            self.assertEqual(
                envelope["data"]["axis"], "reference-demo"
            )
            # 2 findings — both in dirty.md
            findings = envelope["data"]["findings"]
            self.assertEqual(len(findings), 2)
            for f in findings:
                self.assertIn("dirty.md", f["path"])
            # 2 ≤ yellow_max(25) → yellow
            self.assertEqual(envelope["verdict"], "yellow")

    def test_reference_axis_loads_via_stem_resolution(self):
        """`run --axis reference_demo` resolves under domain/axes/."""
        import axis_runner
        spec = axis_runner.load(_REFERENCE_YAML)
        self.assertEqual(spec["name"], "reference-demo")
        self.assertEqual(spec["scan_spec"]["type"], "grep")

if __name__ == "__main__":
    unittest.main()
