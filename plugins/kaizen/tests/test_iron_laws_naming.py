"""Tests for the cli-naming-consistency iron-law.

Split from test_iron_laws.py to keep that file under the 500-line
karpathy threshold; the new law's 4-case behaviour set is large
enough to deserve its own file. Shares the _mini_plugin + _ctx
fixtures by re-importing them.

Law: when a CLI script ships both `ArgumentParser(prog="X")` and
`_envelope.emitter("Y", ...)`, X must equal Y. Otherwise --help
prints one tool-name while trace events carry another — the 3-way
naming-drift class (bin / prog / emitter) at the prog↔emitter axis.
"""

import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN_ROOT = _HERE.parent
_APP = _PLUGIN_ROOT / "skills" / "iron-laws" / "application"
_SCRIPTS = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
for _p in (_HERE, _APP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from test_iron_laws import _mini_plugin, _ctx  # noqa: E402


class TestCliNamingConsistency(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)
        self.pk = _mini_plugin(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def test_clean_when_prog_matches_emitter(self):
        import _iron_laws
        p = self.pk / "scripts/quality/demo.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            'import _envelope\n'
            '_emit = _envelope.emitter("kaizen-demo", tool_version="1.0.0")\n'
            'ap = argparse.ArgumentParser(prog="kaizen-demo")\n'
        )
        self.assertEqual(
            _iron_laws.check_cli_naming_consistency(_ctx(self.tmp)), [])

    def test_flags_prog_emitter_disagreement(self):
        import _iron_laws
        p = self.pk / "scripts/quality/drifty.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        # The exact pattern surfaced 2026-05-20 in 7 files (docs_flow /
        # index_flow / search_flow / observe / trace / config / loop_state):
        # prog used the raw filename; emitter carried the canonical name.
        p.write_text(
            'import _envelope\n'
            '_emit = _envelope.emitter("kaizen-drifty", tool_version="1.0.0")\n'
            'ap = argparse.ArgumentParser(prog="drifty.py")\n'
        )
        findings = _iron_laws.check_cli_naming_consistency(_ctx(self.tmp))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].law_id, "cli-naming-consistency")
        self.assertEqual(findings[0].severity, "soft")
        self.assertIn("drifty.py", findings[0].message)
        self.assertIn("kaizen-drifty", findings[0].message)

    def test_silent_when_one_side_absent(self):
        """Script with only prog OR only emitter is fine — the law only
        opinions when both surfaces exist and disagree."""
        import _iron_laws
        prog_only = self.pk / "scripts/util/prog_only.py"
        prog_only.parent.mkdir(parents=True, exist_ok=True)
        prog_only.write_text(
            'ap = argparse.ArgumentParser(prog="kaizen-prog-only")\n')
        emitter_only = self.pk / "scripts/util/emitter_only.py"
        emitter_only.write_text(
            '_emit = _envelope.emitter("kaizen-emitter-only", tool_version="1.0.0")\n')
        self.assertEqual(
            _iron_laws.check_cli_naming_consistency(_ctx(self.tmp)), [])

    def test_underscore_files_skipped(self):
        """`_*.py` files are private helpers — even if they happen to
        carry a prog/emitter literal in a docstring example, they're
        not the CLI surface and shouldn't be flagged."""
        import _iron_laws
        p = self.pk / "scripts/util/_helper.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            '# example: ArgumentParser(prog="something")\n'
            '_emit = _envelope.emitter("kaizen-helper", tool_version="1.0.0")\n'
            'ap = argparse.ArgumentParser(prog="other")\n'
        )
        self.assertEqual(
            _iron_laws.check_cli_naming_consistency(_ctx(self.tmp)), [])


if __name__ == "__main__":
    unittest.main()
