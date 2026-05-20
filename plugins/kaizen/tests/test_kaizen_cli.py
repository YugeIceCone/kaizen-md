"""Tests for scripts/cli/kaizen_cli.py — unified dispatcher.

Moved from scripts/io/_kaizen_dispatcher.py — the dispatcher isn't an
I/O primitive; it's a CLI surface. scripts/cli/ is the canonical home
for the public dispatch entry-point."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KAIZEN_CLI = _REPO_ROOT / "plugins/kaizen/scripts/cli/kaizen_cli.py"
_BIN_KAIZEN = _REPO_ROOT / "plugins/kaizen/bin/kaizen"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestDispatcherInventory(unittest.TestCase):
    def setUp(self):
        self.cli = _load("kaizen_cli_test", _KAIZEN_CLI)

    def test_list_wrappers_returns_executables(self):
        wrappers = self.cli._list_wrappers()
        self.assertGreater(len(wrappers), 30, "expected many bin wrappers")
        for w in wrappers:
            self.assertTrue(w.name.startswith("kaizen-"))

    def test_kaizen_self_not_listed(self):
        """`bin/kaizen` itself must not appear in the subcommand list."""
        wrappers = self.cli._list_wrappers()
        names = [w.name for w in wrappers]
        self.assertNotIn("kaizen", names)

    def test_categorize_known_subcommands(self):
        self.assertEqual(self.cli._categorize("gatekeeper"), "gate")
        self.assertEqual(self.cli._categorize("backlog"), "workflow")
        self.assertEqual(self.cli._categorize("brain"), "brain")
        self.assertEqual(self.cli._categorize("setup"), "maintenance")

    def test_categorize_unknown_falls_back_to_misc(self):
        self.assertEqual(self.cli._categorize("totally-novel-name"), "misc")

    def test_wrapper_description_extracts_first_comment(self):
        bin_dir = _REPO_ROOT / "plugins/kaizen/bin"
        gatekeeper = bin_dir / "kaizen-gatekeeper"
        desc = self.cli._wrapper_description(gatekeeper)
        self.assertIn("gate", desc.lower())


class TestDispatcherCommands(unittest.TestCase):
    """Subprocess-driven — exercises the bash entry-point too."""

    def test_list_text_runs(self):
        r = subprocess.run([str(_BIN_KAIZEN), "list"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertIn("kaizen v", r.stdout)
        self.assertIn("subcommand", r.stdout)

    def test_list_json_is_valid_json(self):
        r = subprocess.run([str(_BIN_KAIZEN), "list", "--json"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIsInstance(data, dict)
        # Must have at least the canonical categories
        self.assertIn("gate", data)
        self.assertIn("workflow", data)

    def test_version(self):
        r = subprocess.run([str(_BIN_KAIZEN), "version"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0)
        self.assertIn("kaizen v", r.stdout)
        self.assertIn("dispatcher v", r.stdout)

    def test_unknown_subcommand_exits_2(self):
        r = subprocess.run([str(_BIN_KAIZEN), "nonexistent-subcommand"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown subcommand", r.stderr)

    def test_help_includes_wrapper_header_and_passthrough(self):
        r = subprocess.run([str(_BIN_KAIZEN), "help", "gatekeeper"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertIn("=== kaizen-gatekeeper ===", r.stdout)
        self.assertIn("=== wrapper --help (passthrough) ===", r.stdout)
        # Ordering — the wrapper header section must appear BEFORE the
        # passthrough section. Regression guard for the stdout-buffering
        # bug fixed mid-implementation.
        header_pos = r.stdout.index("=== kaizen-gatekeeper ===")
        passthrough_pos = r.stdout.index("=== wrapper --help")
        self.assertLess(header_pos, passthrough_pos,
                        "wrapper header must precede passthrough output")

    def test_dispatch_to_existing_subcommand(self):
        # `kaizen gatekeeper list` should run gatekeeper's `list` command
        # and exit cleanly. This exercises the execv path end-to-end.
        r = subprocess.run([str(_BIN_KAIZEN), "gatekeeper", "list"],
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0)
        # gatekeeper's `list` prints the sub-gate names
        self.assertIn("iron-laws", r.stdout)
        self.assertIn("etu", r.stdout)

    def test_commands_list_runs(self):
        r = subprocess.run([str(_BIN_KAIZEN), "commands"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0)
        self.assertIn("slash commands", r.stdout)
        # Canonical entries we know exist (post-consolidate-2 D3)
        self.assertIn("audit", r.stdout)
        self.assertIn("setup", r.stdout)

    def test_commands_list_json_is_valid(self):
        r = subprocess.run([str(_BIN_KAIZEN), "commands", "list", "--json"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIsInstance(data, list)
        # Every entry has the expected keys
        for entry in data:
            for k in ("name", "slug", "description", "has_bash_body", "bin_wrapper"):
                self.assertIn(k, entry, f"missing key {k} in {entry}")

    def test_commands_show_prints_body(self):
        r = subprocess.run([str(_BIN_KAIZEN), "commands", "show", "audit"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0)
        self.assertIn("---", r.stdout)  # frontmatter delimiter
        self.assertIn("name: audit", r.stdout)

    def test_commands_show_unknown_exits_2(self):
        r = subprocess.run([str(_BIN_KAIZEN), "commands", "show", "nonexistent"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 2)

    def test_commands_show_without_name_errors(self):
        r = subprocess.run([str(_BIN_KAIZEN), "commands", "show"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 2)


class TestSlashCommandInventory(unittest.TestCase):
    def setUp(self):
        self.cli = _load("kaizen_cli_inv_test", _KAIZEN_CLI)

    def test_inventory_returns_list_of_dicts(self):
        cmds = self.cli._list_slash_commands()
        # Post-consolidation steady-state: 8 root slashes + audit:axis
        # sub-namespace. The inventory enumerates the 8 root .md files.
        self.assertGreaterEqual(len(cmds), 8, "expected a populated slash menu")
        for c in cmds:
            self.assertIsInstance(c, dict)
            self.assertIn("name", c)
            self.assertIn("slug", c)

    def test_frontmatter_parser_handles_simple_yaml(self):
        text = '---\nname: foo\ndescription: bar baz\n---\n# body\n'
        fm = self.cli._parse_frontmatter(text)
        self.assertEqual(fm["name"], "foo")
        self.assertEqual(fm["description"], "bar baz")

    def test_bash_body_detection(self):
        cmds = self.cli._list_slash_commands()
        # audit.md is the canonical example of a bash-bodied command
        audit = next(c for c in cmds if c["slug"] == "audit")
        self.assertEqual(audit["has_bash_body"], "true")

    def test_bin_wrapper_link_resolved_when_present(self):
        cmds = self.cli._list_slash_commands()
        audit = next(c for c in cmds if c["slug"] == "audit")
        # audit has bin/kaizen-audit
        self.assertEqual(audit["bin_wrapper"], "kaizen-audit")


class TestPatternsSubcommand(unittest.TestCase):
    """`kaizen patterns` exposes the canonical CLI-patterns catalog
    (declared in skills/plugin-development/domain/cli-patterns.yaml)."""

    def test_patterns_runs_clean(self):
        r = subprocess.run([str(_BIN_KAIZEN), "patterns"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        # human-readable: header + at least a handful of pattern lines
        self.assertIn("CLI patterns", r.stdout)

    def test_patterns_lists_canonical_entries(self):
        r = subprocess.run([str(_BIN_KAIZEN), "patterns"],
                            capture_output=True, text=True, timeout=10)
        for known_id in ("argparse-subparsers", "json-flag",
                          "envelope-emitter", "disable-env-knob"):
            self.assertIn(known_id, r.stdout,
                          f"missing canonical pattern: {known_id}")

    def test_patterns_refresh_dry_run_reports_drift(self):
        """`kaizen patterns --refresh --dry-run` reports outcome
        without writing the file. Two valid response shapes:
        'no change (N patterns scanned)' OR an itemized per-pattern
        delta when drift is present."""
        r = subprocess.run([str(_BIN_KAIZEN), "patterns", "--refresh", "--dry-run"],
                            capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout,
                          r"(?i)(no change|would update|0 patterns updated)")

    def test_patterns_json_returns_structured_catalog(self):
        r = subprocess.run([str(_BIN_KAIZEN), "patterns", "--json"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("patterns", data)
        self.assertIsInstance(data["patterns"], list)
        self.assertGreaterEqual(len(data["patterns"]), 10)
        for p in data["patterns"]:
            for k in ("id", "shape", "count", "why"):
                self.assertIn(k, p, f"pattern {p.get('id','?')} missing {k}")


class TestTimeMode(unittest.TestCase):
    """Standalone — `--time` is a subprocess-driven CLI mode, not
    inventory or commands-discovery related."""

    def test_time_mode_emits_timing(self):
        # --time applies to dispatched WRAPPER subcommands (built-ins
        # like `version`/`list` short-circuit BEFORE the timing block —
        # see _kaizen_dispatcher.py::main for the order).
        r = subprocess.run([str(_BIN_KAIZEN), "--time", "gatekeeper", "list"],
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0)
        # Timing line goes to stderr
        self.assertIn("completed in", r.stderr)
        self.assertIn("ms", r.stderr)


if __name__ == "__main__":
    unittest.main()
