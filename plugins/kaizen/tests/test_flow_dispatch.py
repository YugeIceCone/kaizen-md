"""Tests for flow_cli.py — Tier-2 consolidated flow-family dispatcher.

Covers the kaizen-flow <demo|docs|index|search> verb dispatch. Uses
subprocess (the dispatcher uses os.execvp so in-process testing would
replace the test runner). Heavy-dep verbs (index/search) are tested
only for dispatch reach (the verb header check + tooling presence
check); their actual execution is covered by the underlying script's
own tests.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_FLOW_CLI = _SCRIPTS / "flow_cli.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    """Invoke flow_cli.py with given args via python3 subprocess."""
    return subprocess.run(
        [sys.executable, str(_FLOW_CLI), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestUsage(unittest.TestCase):
    def test_no_args_prints_usage_and_exits_2(self):
        result = _run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: kaizen-flow", result.stdout)
        for verb in ("demo", "docs", "index", "search"):
            self.assertIn(verb, result.stdout)

    def test_help_flag_prints_usage_and_exits_0(self):
        result = _run("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: kaizen-flow", result.stdout)

    def test_short_help_flag_also_works(self):
        result = _run("-h")
        self.assertEqual(result.returncode, 0)


class TestUnknownVerb(unittest.TestCase):
    def test_unknown_verb_exits_2_with_listing(self):
        result = _run("nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown verb", result.stderr)
        self.assertIn("'nope'", result.stderr)
        for verb in ("demo", "docs", "index", "search"):
            self.assertIn(verb, result.stderr)

    def test_unknown_verb_with_args_still_exits_2(self):
        result = _run("does-not-exist", "--apply")
        self.assertEqual(result.returncode, 2)


class TestDispatchDemo(unittest.TestCase):
    """demo verb → flow.py. Uses a temp workspace to avoid side effects."""

    def test_demo_runs_on_temp_workspace(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = _run("demo", tmp)
            # flow.py demo is a no-LLM-no-deps reference pipeline;
            # should exit 0 on a clean empty workspace.
            self.assertEqual(
                result.returncode, 0,
                f"demo verb failed; stdout={result.stdout}; stderr={result.stderr}",
            )


class TestDispatchDocs(unittest.TestCase):
    """docs verb → docs_flow.py. --help is read-only."""

    def test_docs_help_reaches_docs_flow(self):
        result = _run("docs", "--help")
        # docs_flow.py's argparse owns surface; what matters is dispatch
        # produced output from docs_flow (not from flow_cli itself).
        self.assertNotIn("kaizen-flow: unknown verb", result.stderr)
        self.assertNotIn("usage: kaizen-flow <verb>", result.stdout)


class TestConsolidatedCliParentHeaders(unittest.TestCase):
    """Iron-law contract: dispatched scripts declare the parent."""

    def test_flow_has_consolidated_cli_parent_header(self):
        body = (_SCRIPTS / "flow.py").read_text(encoding="utf-8")
        self.assertIn("# consolidated-cli-parent: flow", body[:200])

    def test_docs_flow_has_consolidated_cli_parent_header(self):
        body = (_SCRIPTS / "docs_flow.py").read_text(encoding="utf-8")
        self.assertIn("# consolidated-cli-parent: flow", body[:200])

    def test_index_flow_has_consolidated_cli_parent_header(self):
        body = (_SCRIPTS / "index_flow.py").read_text(encoding="utf-8")
        self.assertIn("# consolidated-cli-parent: flow", body[:200])

    def test_search_flow_has_consolidated_cli_parent_header(self):
        body = (_SCRIPTS / "search_flow.py").read_text(encoding="utf-8")
        self.assertIn("# consolidated-cli-parent: flow", body[:200])


class TestDispatcherCompiles(unittest.TestCase):
    """Catches syntax errors in CI envs that lack runtime deps."""

    def test_flow_cli_module_parses(self):
        body = _FLOW_CLI.read_text(encoding="utf-8")
        compile(body, str(_FLOW_CLI), "exec")


if __name__ == "__main__":
    unittest.main()
