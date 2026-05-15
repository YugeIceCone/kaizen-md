"""Tests for the iron-laws skill — loader, codegen, checker, CLI, MCP.

The iron-laws skill's backing code is split across two dirs:
  - skills/iron-laws/application/  — _loader.py, codegen.py
  - skills/workflow/scripts/       — _iron_laws.py, iron_laws.py, iron_laws_mcp.py
Both are put on sys.path here.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_APP = _PLUGIN_ROOT / "skills" / "iron-laws" / "application"
_SCRIPTS = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
_DOMAIN = _PLUGIN_ROOT / "skills" / "iron-laws" / "domain"
for _p in (_APP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class TestLoader(unittest.TestCase):
    def test_load_laws_returns_all(self):
        import _loader
        laws = _loader.load_laws()
        self.assertEqual(len(laws), 21)

    def test_every_law_has_required_fields(self):
        import _loader
        for law in _loader.load_laws():
            for field in ("id", "statement", "severity", "enforcement", "why"):
                self.assertIn(field, law, f"{law.get('id')} missing {field}")

    def test_auto_laws_have_check_manual_do_not(self):
        import _loader
        for law in _loader.load_laws():
            if law["enforcement"] == "auto":
                self.assertTrue(law.get("check"), f"{law['id']} auto but no check")
            else:
                self.assertNotIn("check", law, f"{law['id']} manual but has check")

    def test_load_laws_by_id(self):
        import _loader
        by_id = _loader.load_laws_by_id()
        self.assertIn("no-modify-vendored", by_id)
        self.assertEqual(by_id["no-modify-vendored"]["severity"], "hard")

    def test_auto_and_manual_filters(self):
        import _loader
        auto = _loader.auto_laws()
        manual = _loader.manual_laws()
        self.assertEqual(len(auto), 15)
        self.assertEqual(len(manual), 6)
        self.assertTrue(all(l["enforcement"] == "auto" for l in auto))

    def test_load_laws_rejects_schema_invalid(self):
        import _loader
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False
        ) as fh:
            fh.write("version: 1\nlaws:\n  - id: bad\n")  # missing required fields
            bad = fh.name
        try:
            with self.assertRaises(Exception):
                _loader.load_laws(path=Path(bad))
        finally:
            Path(bad).unlink()


def _mini_plugin(tmp: Path) -> Path:
    """Build a minimal repo skeleton: <tmp>/plugins/kaizen/{skills,hooks,bin,commands,...}."""
    pk = tmp / "plugins" / "kaizen"
    for d in ("skills/workflow/scripts", "skills/demo", "hooks/claude",
              "bin", "commands", "tests", ".claude-plugin"):
        (pk / d).mkdir(parents=True, exist_ok=True)
    (pk / ".claude-plugin" / "plugin.json").write_text('{"permissions": {"allow": []}}')
    (pk / "hooks" / "hooks.json").write_text('{"hooks": {}}')
    return pk


def _ctx(tmp: Path, scope="all", changed=None, added=None):
    import _iron_laws
    changed = changed or []
    return _iron_laws.CheckContext(
        repo_root=tmp,
        plugin_root=tmp / "plugins" / "kaizen",
        scope=scope,
        changed=changed,
        # in these fixtures the changed files ARE the added files unless
        # a test overrides `added` explicitly.
        added=added if added is not None else changed,
    )


class TestChecker(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)
        self.pk = _mini_plugin(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def test_hook_bypass_knob(self):
        import _iron_laws
        good = self.pk / "hooks/claude/demo-hook.sh"
        good.write_text('#!/bin/bash\n[ -n "$KAIZEN_DEMO_DISABLE" ] && exit 0\n')
        self.assertEqual(_iron_laws.check_hook_bypass_knob(_ctx(self.tmp)), [])
        good.write_text('#!/bin/bash\necho hi\n')
        self.assertTrue(_iron_laws.check_hook_bypass_knob(_ctx(self.tmp)))

    def test_every_hook_script_traces_its_firing(self):
        import _iron_laws
        h = self.pk / "hooks/claude/demo-hook.sh"
        h.write_text('#!/bin/bash\nbash "$D/_trace.sh" demo\n')
        self.assertEqual(_iron_laws.check_every_hook_script_traces_its_firing(_ctx(self.tmp)), [])
        h.write_text('#!/bin/bash\necho hi\n')
        self.assertTrue(_iron_laws.check_every_hook_script_traces_its_firing(_ctx(self.tmp)))

    def test_skill_md_no_exec_markers(self):
        import _iron_laws
        s = self.pk / "skills/demo/SKILL.md"
        s.write_text("# Demo\n\nrun the thing normally.\n")
        self.assertEqual(_iron_laws.check_skill_md_no_exec_markers(_ctx(self.tmp)), [])
        s.write_text("# Demo\n\n!`bash -c 'echo hi'`\n")
        self.assertTrue(_iron_laws.check_skill_md_no_exec_markers(_ctx(self.tmp)))

    def test_skill_md_no_external_script_paths(self):
        import _iron_laws
        s = self.pk / "skills/demo/SKILL.md"
        s.write_text("# Demo\n\n```bash\npython3 ${CLAUDE_PLUGIN_ROOT}/x.py\n```\n")
        self.assertEqual(_iron_laws.check_skill_md_no_external_script_paths(_ctx(self.tmp)), [])
        s.write_text("# Demo\n\n```bash\n~/.claude/scripts/.venv/bin/python3 x.py\n```\n")
        self.assertTrue(_iron_laws.check_skill_md_no_external_script_paths(_ctx(self.tmp)))

    def test_lazy_heavy_deps(self):
        import _iron_laws
        p = self.pk / "skills/workflow/scripts/demo.py"
        p.write_text("try:\n    import torch\nexcept ImportError:\n    torch = None\n")
        self.assertEqual(_iron_laws.check_lazy_heavy_deps(_ctx(self.tmp)), [])
        p.write_text("import torch\nprint(torch)\n")
        self.assertTrue(_iron_laws.check_lazy_heavy_deps(_ctx(self.tmp)))

    def test_sandbox_tests(self):
        import _iron_laws
        t = self.pk / "tests/test_demo.py"
        t.write_text("import os\nP = os.environ['KAIZEN_DEMO_PATH']\n")
        self.assertEqual(_iron_laws.check_sandbox_tests(_ctx(self.tmp)), [])
        t.write_text("from pathlib import Path\n(Path.home() / '.claude' / 'x').write_text('y')\n")
        self.assertTrue(_iron_laws.check_sandbox_tests(_ctx(self.tmp)))

    def test_slash_command_args_no_default_spaces(self):
        import _iron_laws
        c = self.pk / "commands/demo.md"
        c.write_text("---\nname: demo\n---\nrun $ARGUMENTS\n")
        self.assertEqual(_iron_laws.check_slash_command_args_no_default_spaces(_ctx(self.tmp)), [])
        c.write_text("---\nname: demo\n---\nrun ${ARGUMENTS:-lifetime --since 7d}\n")
        self.assertTrue(_iron_laws.check_slash_command_args_no_default_spaces(_ctx(self.tmp)))

    def test_no_modify_vendored(self):
        import _iron_laws
        clean = _ctx(self.tmp, scope="staged",
                     changed=["plugins/kaizen/skills/demo/SKILL.md"])
        self.assertEqual(_iron_laws.check_no_modify_vendored(clean), [])
        dirty = _ctx(self.tmp, scope="staged",
                     changed=["plugins/kaizen/skills/kiss/SKILL.md"])
        self.assertTrue(_iron_laws.check_no_modify_vendored(dirty))

    def test_bin_wrapper_per_cli(self):
        import _iron_laws
        p = self.pk / "skills/workflow/scripts/demo.py"
        p.write_text("import argparse\nif __name__ == '__main__':\n    argparse.ArgumentParser()\n")
        # no bin wrapper → finding
        self.assertTrue(_iron_laws.check_bin_wrapper_per_cli(_ctx(self.tmp)))
        (self.pk / "bin" / "kaizen-demo").write_text("#!/bin/bash\n")
        self.assertEqual(_iron_laws.check_bin_wrapper_per_cli(_ctx(self.tmp)), [])

    def test_plugin_manifest_permissions(self):
        import _iron_laws
        (self.pk / "skills/workflow/scripts/demo.py").write_text("print('hi')\n")
        changed = ["plugins/kaizen/skills/workflow/scripts/demo.py"]
        dirty = _ctx(self.tmp, scope="staged", changed=changed)
        self.assertTrue(_iron_laws.check_plugin_manifest_permissions(dirty))
        (self.pk / ".claude-plugin" / "plugin.json").write_text(
            '{"permissions": {"allow": ["Bash(python3 x/demo.py:*)"]}}')
        self.assertEqual(_iron_laws.check_plugin_manifest_permissions(dirty), [])

    def test_paired_tests(self):
        import _iron_laws
        (self.pk / "skills/workflow/scripts/demo.py").write_text("print('hi')\n")
        changed = ["plugins/kaizen/skills/workflow/scripts/demo.py"]
        self.assertTrue(_iron_laws.check_paired_tests(_ctx(self.tmp, "staged", changed)))
        (self.pk / "tests/test_demo.py").write_text("# test\n")
        self.assertEqual(
            _iron_laws.check_paired_tests(_ctx(self.tmp, "staged", changed)), [])

    def test_bin_wrapper_per_cli_strict(self):
        import _iron_laws
        (self.pk / "skills/workflow/scripts/demo.py").write_text(
            "import argparse\nif __name__ == '__main__':\n    argparse.ArgumentParser()\n")
        changed = ["plugins/kaizen/skills/workflow/scripts/demo.py"]
        self.assertTrue(_iron_laws.check_bin_wrapper_per_cli_strict(_ctx(self.tmp, "staged", changed)))
        (self.pk / "bin" / "kaizen-demo").write_text("#!/bin/bash\n")
        changed.append("plugins/kaizen/bin/kaizen-demo")
        self.assertEqual(
            _iron_laws.check_bin_wrapper_per_cli_strict(_ctx(self.tmp, "staged", changed)), [])

    def test_hooks_json_additive_event_multi_command(self):
        import _iron_laws
        good = {"hooks": {"SessionEnd": [{"matcher": "*", "hooks": [{"x": 1}, {"y": 2}]}]}}
        (self.pk / "hooks/hooks.json").write_text(json.dumps(good))
        self.assertEqual(_iron_laws.check_hooks_json_additive_event_multi_command(_ctx(self.tmp)), [])
        bad = {"hooks": {"SessionEnd": [
            {"matcher": "*", "hooks": [{"x": 1}]}, {"matcher": "*", "hooks": [{"y": 2}]}]}}
        (self.pk / "hooks/hooks.json").write_text(json.dumps(bad))
        self.assertTrue(_iron_laws.check_hooks_json_additive_event_multi_command(_ctx(self.tmp)))

    def test_claude_md_no_volatile_data(self):
        import _iron_laws
        cm = self.tmp / "CLAUDE.md"
        cm.write_text("# CLAUDE.md\n\nThe durable rulebook. No volatile data here.\n")
        self.assertEqual(_iron_laws.check_claude_md_no_volatile_data(_ctx(self.tmp)), [])
        cm.write_text("# CLAUDE.md\n\nLanded in commit a1b2c3d4e5f6 on 2026-05-14.\n")
        self.assertTrue(_iron_laws.check_claude_md_no_volatile_data(_ctx(self.tmp)))

    def test_node_flow_for_multi_step(self):
        import _iron_laws
        p = self.pk / "skills/workflow/scripts/demo.py"
        p.write_text("import asyncio\nasync def f():\n    await asyncio.gather(a())\n")
        self.assertEqual(_iron_laws.check_node_flow_for_multi_step(_ctx(self.tmp)), [])
        p.write_text(
            "import asyncio\n"
            "async def f():\n    await asyncio.gather(a())\n"
            "async def g():\n    await asyncio.gather(b())\n")
        self.assertTrue(_iron_laws.check_node_flow_for_multi_step(_ctx(self.tmp)))


class TestRegistryIntegrity(unittest.TestCase):
    def test_every_auto_law_has_a_check_fn(self):
        import _loader, _iron_laws
        for law in _loader.auto_laws():
            self.assertIn(law["check"], _iron_laws.CHECKS,
                          f"auto law {law['id']} has no check_* fn registered")

    def test_no_orphan_check_fns(self):
        import _loader, _iron_laws
        declared = {law["check"] for law in _loader.auto_laws()}
        for name in _iron_laws.CHECKS:
            self.assertIn(name, declared, f"check fn {name} maps to no auto law")

    def test_run_checks_dispatches_only_auto(self):
        import _iron_laws
        # run_checks on a clean repo skeleton returns a list (no crash)
        result = _iron_laws.run_checks(scope="all", repo_root=Path.cwd())
        self.assertIsInstance(result, list)


class TestCLI(unittest.TestCase):
    CLI = _SCRIPTS / "iron_laws.py"

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(self.CLI), *args],
            capture_output=True, text=True, cwd=str(_PLUGIN_ROOT))

    def test_list_prints_all_laws(self):
        r = self._run("list")
        self.assertEqual(r.returncode, 0)
        rows = [ln for ln in r.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(rows), 21)

    def test_no_arg_defaults_to_list(self):
        r = self._run()
        self.assertEqual(r.returncode, 0)
        self.assertIn("no-modify-vendored", r.stdout)

    def test_show_prints_one_law(self):
        r = self._run("show", "hook-bypass-knob")
        self.assertEqual(r.returncode, 0)
        self.assertIn("hook-bypass-knob", r.stdout)
        self.assertIn("KAIZEN", r.stdout)

    def test_show_unknown_id_exits_nonzero(self):
        r = self._run("show", "no-such-law-xyz")
        self.assertNotEqual(r.returncode, 0)

    def test_check_all_does_not_crash(self):
        r = self._run("check", "--all")
        self.assertIn(r.returncode, (0, 1))

    def test_render_regenerates_cleanly(self):
        r = self._run("render")
        self.assertEqual(r.returncode, 0)


try:
    import mcp as _mcp_pkg  # noqa: F401
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


@unittest.skipUnless(_MCP_AVAILABLE, "mcp package not installed")
class TestMCP(unittest.TestCase):
    def _mod(self):
        import asyncio
        if "iron_laws_mcp" in sys.modules:
            del sys.modules["iron_laws_mcp"]
        import iron_laws_mcp
        return iron_laws_mcp, asyncio

    def test_list_returns_all_laws(self):
        m, aio = self._mod()
        laws = aio.run(m.iron_laws_list())
        self.assertEqual(len(laws), 21)

    def test_show_returns_one_law(self):
        m, aio = self._mod()
        law = aio.run(m.iron_laws_show("hook-bypass-knob"))
        self.assertEqual(law["id"], "hook-bypass-knob")
        self.assertEqual(law["enforcement"], "auto")

    def test_show_unknown_returns_error(self):
        m, aio = self._mod()
        out = aio.run(m.iron_laws_show("no-such-law-xyz"))
        self.assertIn("error", out)

    def test_check_returns_findings_list(self):
        m, aio = self._mod()
        out = aio.run(m.iron_laws_check(scope="all"))
        self.assertIn("findings", out)
        self.assertIsInstance(out["findings"], list)


class TestMCPRegistration(unittest.TestCase):
    def test_mcp_json_lists_iron_laws_server(self):
        data = json.loads((_PLUGIN_ROOT / ".mcp.json").read_text())
        # All domain servers are composed through the kaizen gateway
        self.assertIn("kaizen", data["mcpServers"])
        joined = " ".join(data["mcpServers"]["kaizen"]["args"])
        self.assertIn("gateway.py", joined)
        import gateway
        module_names = [m for _, m in gateway.SUBSERVERS]
        self.assertIn("iron_laws_mcp", module_names)


class TestCodegen(unittest.TestCase):
    def test_render_is_deterministic(self):
        import codegen
        self.assertEqual(codegen._render(), codegen._render())

    def test_check_passes_when_reference_in_sync(self):
        import codegen
        # references/iron-laws.md is committed in-sync; --check must pass.
        self.assertEqual(codegen.generate(check_only=True), 0)

    def test_check_detects_drift(self):
        import codegen
        original = codegen.REF_PATH
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".md", delete=False
            ) as fh:
                fh.write("stale content — not what _render() produces\n")
                stale = fh.name
            codegen.REF_PATH = Path(stale)
            self.assertEqual(codegen.generate(check_only=True), 1)
        finally:
            codegen.REF_PATH = original
            Path(stale).unlink()

    def test_generated_reference_has_do_not_edit_header(self):
        ref = (_DOMAIN.parent / "references" / "iron-laws.md").read_text()
        self.assertIn("DO NOT HAND-EDIT", ref)
        self.assertIn("21 laws", ref)


if __name__ == "__main__":
    unittest.main()
