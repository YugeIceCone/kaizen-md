"""Unit tests for `export_target.py` — the cross-CLI bundle exporter.

1:1 coverage of every public surface:

    parse_frontmatter            → frontmatter splitter
    substitute_plugin_root       → ${CLAUDE_PLUGIN_ROOT} → ${KAIZEN_PLUGIN_ROOT}
    render_frontmatter           → re-emit YAML+body
    emit_toml_table              → TOML mini-emitter
    agent_md_to_toml             → kaizen agent .md → Codex .toml
    mcp_servers_to_toml          → .mcp.json → Codex config.toml
    CodexExporter.export_skills  → walk skills/<n>/SKILL.md → skills/<n>.md
    CodexExporter.export_commands→ walk commands/*.md
    CodexExporter.export_agents  → walk agents/*.md → agents/*.toml
    CodexExporter.export_mcp     → .mcp.json → config.toml
    CodexExporter.export_readme  → README.md install guide
    CodexExporter.run            → orchestrator returns ExportResult
    main(argv)                   → CLI entrypoint

Each helper exercised against a synthetic plugin tree built in tmpdir.

Run:
    python3 -m unittest tests.test_export_target -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import export_target as et  # noqa: E402

# ─── Synthetic plugin builder ────────────────────────────────────────

def _make_plugin(root: Path) -> Path:
    """Build a minimal kaizen-shaped plugin tree under ``root``."""
    plugin = root / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text('{"name":"kaizen-test"}\n')

    skills = plugin / "skills" / "alpha"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: alpha skill\n---\n"
        "Body referencing ${CLAUDE_PLUGIN_ROOT}/scripts/x.py.\n"
    )

    skills_beta = plugin / "skills" / "beta"
    skills_beta.mkdir(parents=True)
    (skills_beta / "SKILL.md").write_text("---\nname: beta\ndescription: beta\n---\nbeta body\n")

    commands = plugin / "commands"
    commands.mkdir(parents=True)
    (commands / "demo.md").write_text(
        "---\nname: demo\ndescription: demo cmd\n---\n"
        "!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/demo.py`\n"
    )

    agents = plugin / "agents"
    agents.mkdir(parents=True)
    (agents / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: |\n  A reviewer agent.\n  Multi-line.\n"
        "tools:\n  - Read\n  - Grep\nmodel: claude-opus-4-7\n---\n"
        "Body text after frontmatter.\n"
    )

    (plugin / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "backlog": {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/b.py"]},
            "lint": {"command": "uv", "args": ["run", "${CLAUDE_PLUGIN_ROOT}/scripts/l.py"]},
        }
    }))
    return plugin

# ─── Pure helpers ────────────────────────────────────────────────────

class TestParseFrontmatter(unittest.TestCase):
    def test_parses_yaml_block(self):
        fm = et.parse_frontmatter("---\nname: x\nfoo: 1\n---\nbody\n")
        self.assertEqual(fm.data, {"name": "x", "foo": 1})
        self.assertEqual(fm.body, "body\n")

    def test_no_frontmatter_returns_empty_data(self):
        fm = et.parse_frontmatter("no frontmatter here\n")
        self.assertEqual(fm.data, {})
        self.assertEqual(fm.body, "no frontmatter here\n")

    def test_malformed_frontmatter_falls_back(self):
        # Non-dict YAML parse should not crash the exporter.
        fm = et.parse_frontmatter("---\n- just a list\n---\nbody\n")
        self.assertEqual(fm.data, {})

class TestSubstitutePluginRoot(unittest.TestCase):
    def test_replaces_all_occurrences(self):
        text = "${CLAUDE_PLUGIN_ROOT}/a and ${CLAUDE_PLUGIN_ROOT}/b"
        self.assertEqual(
            et.substitute_plugin_root(text),
            "${KAIZEN_PLUGIN_ROOT}/a and ${KAIZEN_PLUGIN_ROOT}/b",
        )

    def test_no_match_passthrough(self):
        text = "no var here"
        self.assertEqual(et.substitute_plugin_root(text), text)

    def test_constants_are_distinct(self):
        # Lock the rename direction so a refactor doesn't accidentally
        # collapse the two strings.
        self.assertNotEqual(et.PLUGIN_VAR_FROM, et.PLUGIN_VAR_TO)
        self.assertEqual(et.PLUGIN_VAR_FROM, "${CLAUDE_PLUGIN_ROOT}")
        self.assertEqual(et.PLUGIN_VAR_TO, "${KAIZEN_PLUGIN_ROOT}")

    def test_zwsp_protected_occurrences_pass_through(self):
        # The `command-development` skill documents the substitution
        # mechanism with a zero-width-space wedged after the `$`. That
        # encoding tells Claude Code's processor "don't substitute" —
        # and our exporter must respect it too (the docs continue to
        # describe the original CC behaviour, not Codex's).
        zwsp = "​"
        text = f"$ARGUMENTS, ${zwsp}{{CLAUDE_PLUGIN_ROOT}}"
        self.assertEqual(et.substitute_plugin_root(text), text)

class TestRenderFrontmatter(unittest.TestCase):
    def test_roundtrip_preserves_order_of_keys(self):
        data = {"name": "x", "description": "y", "tools": ["A", "B"]}
        rendered = et.render_frontmatter(data, "body\n")
        self.assertTrue(rendered.startswith("---\n"))
        self.assertIn("name: x", rendered)
        self.assertIn("body\n", rendered)

    def test_empty_data_returns_body_only(self):
        self.assertEqual(et.render_frontmatter({}, "body"), "body")

class TestEmitTomlTable(unittest.TestCase):
    def test_basic_types(self):
        out = et.emit_toml_table("t", {"s": "hi", "i": 1, "f": 1.5, "b": True})
        self.assertIn("[t]", out)
        self.assertIn('s = "hi"', out)
        self.assertIn("i = 1", out)
        self.assertIn("b = true", out)

    def test_list_of_strings(self):
        out = et.emit_toml_table(None, {"args": ["a", "b"]})
        self.assertEqual(out, 'args = ["a", "b"]')

    def test_skips_none_values(self):
        out = et.emit_toml_table(None, {"a": "x", "b": None})
        self.assertEqual(out, 'a = "x"')

    def test_multiline_string_uses_triple_quotes(self):
        out = et.emit_toml_table(None, {"d": "line1\nline2"})
        self.assertIn('"""', out)
        self.assertIn("line1", out)
        self.assertIn("line2", out)

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            et.emit_toml_table(None, {"x": {"nested": "dict"}})

# ─── Codex shape converters ──────────────────────────────────────────

class TestAgentMdToToml(unittest.TestCase):
    def test_basic_mapping(self):
        md = (
            "---\nname: reviewer\ndescription: a reviewer\n"
            "tools:\n  - Read\nmodel: claude-opus-4-7\n---\nBody.\n"
        )
        toml = et.agent_md_to_toml(md)
        self.assertIn('nickname = "reviewer"', toml)
        self.assertIn("a reviewer", toml)
        self.assertIn('model = "claude-opus-4-7"', toml)
        self.assertIn('tools = ["Read"]', toml)

    def test_body_becomes_comment_block(self):
        md = "---\nname: x\n---\nBody line.\n"
        toml = et.agent_md_to_toml(md)
        self.assertIn("# Body line.", toml)

    def test_multiline_description(self):
        md = "---\nname: x\ndescription: |\n  Line A.\n  Line B.\n---\n"
        toml = et.agent_md_to_toml(md)
        self.assertIn("Line A.", toml)
        self.assertIn("Line B.", toml)
        # Multi-line descriptions use TOML triple-quoted strings.
        self.assertIn('"""', toml)

    def test_unknown_keys_pass_through(self):
        md = "---\nname: x\ncustom_thing: 42\n---\n"
        toml = et.agent_md_to_toml(md)
        self.assertIn("custom_thing = 42", toml)

class TestMcpServersToToml(unittest.TestCase):
    def test_one_server_per_table(self):
        toml = et.mcp_servers_to_toml({
            "mcpServers": {
                "backlog": {"command": "python3", "args": ["a.py"]},
                "lint": {"command": "uv", "args": ["run", "l.py"]},
            }
        })
        self.assertIn("[mcp_servers.backlog]", toml)
        self.assertIn("[mcp_servers.lint]", toml)
        self.assertIn('command = "python3"', toml)
        self.assertIn('command = "uv"', toml)

    def test_args_run_through_substitution(self):
        toml = et.mcp_servers_to_toml({
            "mcpServers": {
                "x": {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/a.py"]}
            }
        })
        self.assertIn("${KAIZEN_PLUGIN_ROOT}", toml)
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", toml)

    def test_empty_mcp_json(self):
        # No servers → empty render (no tables) but still terminates cleanly.
        toml = et.mcp_servers_to_toml({"mcpServers": {}})
        self.assertEqual(toml.strip(), "")

# ─── CodexExporter (end-to-end) ──────────────────────────────────────

class TestCodexExporter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugin = _make_plugin(self.root)
        self.out = self.root / "out"
        self.out.mkdir()
        self.exporter = et.CodexExporter(self.plugin, self.out)

    def test_export_skills_walks_all_skill_dirs(self):
        written = self.exporter.export_skills()
        self.assertEqual({p.name for p in written}, {"alpha.md", "beta.md"})

    def test_export_skills_substitutes_plugin_root(self):
        self.exporter.export_skills()
        alpha = (self.out / "skills" / "alpha.md").read_text()
        self.assertIn("${KAIZEN_PLUGIN_ROOT}", alpha)
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", alpha)

    def test_export_skills_appends_provenance_footer(self):
        self.exporter.export_skills()
        alpha = (self.out / "skills" / "alpha.md").read_text()
        self.assertIn("kaizen-export source: skills/alpha/SKILL.md", alpha)

    def test_export_commands_walks_all_files(self):
        written = self.exporter.export_commands()
        self.assertEqual([p.name for p in written], ["demo.md"])
        demo = (self.out / "commands" / "demo.md").read_text()
        self.assertIn("${KAIZEN_PLUGIN_ROOT}", demo)

    def test_export_agents_emits_toml(self):
        written = self.exporter.export_agents()
        self.assertEqual([p.name for p in written], ["reviewer.toml"])
        body = written[0].read_text()
        self.assertIn('nickname = "reviewer"', body)
        self.assertIn('model = "claude-opus-4-7"', body)
        self.assertIn("kaizen-export source: agents/reviewer.md", body)

    def test_export_mcp_emits_config_toml(self):
        path = self.exporter.export_mcp()
        self.assertIsNotNone(path)
        body = path.read_text()
        self.assertIn("[mcp_servers.backlog]", body)
        self.assertIn("[mcp_servers.lint]", body)
        # And path substitution happens through this surface too.
        self.assertIn("${KAIZEN_PLUGIN_ROOT}", body)

    def test_export_readme_emits(self):
        path = self.exporter.export_readme()
        body = path.read_text()
        self.assertIn("kaizen-export", body)
        self.assertIn("KAIZEN_PLUGIN_ROOT", body)
        # Names the source plugin root so users know what they exported.
        self.assertIn(str(self.plugin), body)

    def test_run_returns_full_export_result(self):
        result = self.exporter.run()
        self.assertEqual(len(result.skills), 2)
        self.assertEqual(len(result.commands), 1)
        self.assertEqual(len(result.agents), 1)
        self.assertIsNotNone(result.config_toml)
        self.assertIsNotNone(result.readme)

    def test_dry_run_writes_nothing(self):
        dry = et.CodexExporter(self.plugin, self.out / "dry", dry_run=True)
        result = dry.run()
        # Result lists destinations, but no files were created.
        self.assertEqual(len(result.skills), 2)
        self.assertFalse((self.out / "dry" / "skills" / "alpha.md").exists())

# ─── CLI ─────────────────────────────────────────────────────────────

class TestValidateBundle(unittest.TestCase):
    """Re-parse the emitted bundle to catch encoder bugs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugin = _make_plugin(self.root)
        self.out = self.root / "out"
        et.CodexExporter(self.plugin, self.out).run()

    def test_reports_ok_on_well_formed_export(self):
        report = et.validate_bundle(self.out)
        self.assertTrue(report.ok, msg=report.render(self.out))
        self.assertEqual(report.toml_errors, [])
        self.assertEqual(report.md_frontmatter_warnings, [])
        self.assertGreater(report.toml_files, 0)
        self.assertGreater(report.md_files, 0)

    def test_reports_failure_on_corrupted_toml(self):
        broken = self.out / "agents" / "broken.toml"
        broken.write_text('nickname = "x\n')  # unterminated string
        report = et.validate_bundle(self.out)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.toml_errors), 1)
        self.assertIn("broken.toml", str(report.toml_errors[0][0]))

    def test_reports_warning_on_corrupted_frontmatter(self):
        # Write a .md that starts with --- but has unparseable YAML.
        # This is a source-quality issue (kaizen source files do this
        # with unquoted colons in descriptions), not an encoder bug —
        # so it's a warning, not an error.
        bad = self.out / "skills" / "bad.md"
        bad.write_text("---\n: ; this is not yaml ::\n---\nbody")
        report = et.validate_bundle(self.out)
        # Warnings don't flip ok → False.
        self.assertTrue(report.ok)
        self.assertTrue(any("bad.md" in str(p) for p, _ in report.md_frontmatter_warnings))

    def test_render_includes_summary_lines(self):
        text = et.validate_bundle(self.out).render(self.out)
        self.assertIn("toml files", text)
        self.assertIn("md  files", text)
        self.assertIn("PASS", text)

class TestCli(unittest.TestCase):
    def test_main_exits_2_when_plugin_root_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            rc = et.main(["--target", "codex", "--out", td, "--plugin-root", td])
            self.assertEqual(rc, 2)

    def test_main_exits_2_when_out_missing(self):
        with tempfile.TemporaryDirectory() as td:
            plugin = _make_plugin(Path(td))
            rc = et.main(["--target", "codex", "--plugin-root", str(plugin)])
            self.assertEqual(rc, 2)

    def test_main_validate_flag_returns_zero_on_clean_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = _make_plugin(root)
            out = root / "out"
            rc = et.main([
                "--target", "codex",
                "--out", str(out),
                "--plugin-root", str(plugin),
                "--validate",
            ])
            self.assertEqual(rc, 0)

    def test_main_validate_flag_returns_one_on_broken_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = _make_plugin(root)
            out = root / "out"
            # Run the export, then write a corrupted file to a path the
            # re-export won't overwrite (the exporter writes per-source,
            # so an unrelated file in the same dir survives).
            et.main([
                "--target", "codex",
                "--out", str(out),
                "--plugin-root", str(plugin),
            ])
            (out / "agents" / "broken.toml").write_text('nickname = "broken\n')
            rc = et.main([
                "--target", "codex",
                "--out", str(out),
                "--plugin-root", str(plugin),
                "--validate",
            ])
            self.assertEqual(rc, 1)

    def test_main_runs_codex_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = _make_plugin(root)
            out = root / "out"
            rc = et.main([
                "--target", "codex",
                "--out", str(out),
                "--plugin-root", str(plugin),
            ])
            self.assertEqual(rc, 0)
            self.assertTrue((out / "skills" / "alpha.md").exists())
            self.assertTrue((out / "agents" / "reviewer.toml").exists())
            self.assertTrue((out / "config.toml").exists())
            self.assertTrue((out / "README.md").exists())

    def test_main_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = _make_plugin(root)
            out = root / "out-dry"
            rc = et.main([
                "--target", "codex",
                "--out", str(out),
                "--plugin-root", str(plugin),
                "--dry-run",
            ])
            self.assertEqual(rc, 0)
            self.assertFalse((out / "skills" / "alpha.md").exists())

    def test_main_clean_wipes_existing_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = _make_plugin(root)
            out = root / "out"
            out.mkdir()
            stale = out / "stale.txt"
            stale.write_text("stale")
            rc = et.main([
                "--target", "codex",
                "--out", str(out),
                "--plugin-root", str(plugin),
                "--clean",
            ])
            self.assertEqual(rc, 0)
            self.assertFalse(stale.exists())

if __name__ == "__main__":
    unittest.main()
