"""Regression tests for the planner + blueprint surface.

Catches the class of bug each one was authored to prevent — if any
test in this file goes RED, the cross-cutting invariant it pins has
silently regressed.

Run:
    python3 -m unittest tests.test_blueprint_regressions -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PLUGIN_ROOT.parent.parent
TEMPLATES_DIR = REPO_ROOT / ".kaizen" / "docs" / "templates"
SCHEMAS_DIR = PLUGIN_ROOT / "schemas"
AGENTS_DIR = PLUGIN_ROOT / "agents"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"


class TestBlueprintSchemaInvariant(unittest.TestCase):
    """The blueprint.schema.json + the example + the unification plan
    must continue to validate against each other."""

    def test_blueprint_example_validates(self):
        """The example uses placeholder strings (cc_session_sha256 is a
        literal '<set at write time>' marker). Validate STRUCTURE
        only; skip pattern format checks."""
        import jsonschema
        schema = json.loads((TEMPLATES_DIR / "blueprint.schema.json")
                            .read_text())
        data = json.loads((TEMPLATES_DIR / "blueprint.example.json")
                          .read_text())
        # Relax pattern-format checks — the example has placeholder
        # text in pattern-constrained fields (sha256 placeholder, etc.)
        # Strip patterns from a copy of the schema for this test only.
        def _strip_patterns(node):
            if isinstance(node, dict):
                node.pop("pattern", None)
                for v in node.values():
                    _strip_patterns(v)
            elif isinstance(node, list):
                for v in node:
                    _strip_patterns(v)
        import copy
        relaxed = copy.deepcopy(schema)
        _strip_patterns(relaxed)
        jsonschema.validate(data, relaxed)

    def test_blueprint_template_validates(self):
        """The fillable scaffold must itself be valid blueprint v1."""
        import jsonschema
        schema = json.loads((TEMPLATES_DIR / "blueprint.schema.json")
                            .read_text())
        data = json.loads((TEMPLATES_DIR / "blueprint-template.json")
                          .read_text())
        # Placeholders aren't filled, so we only assert schema-level
        # shape compliance — fields like generated_at use placeholder
        # strings ("<YYYY-MM-DDTHH:MM:SSZ>") which fail format=date-time.
        # Relax by stripping format validation.
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=None,  # skip date-time / date format checks
        )
        validator.validate(data)

    def test_unify_plan_validates_and_dag_clean(self):
        """The session's dogfood plan stays schema-valid + DAG-clean."""
        import jsonschema
        plan_path = (REPO_ROOT / ".kaizen" / "docs" / "plans"
                     / "2026-05-20-unify-artifact-generation.json")
        if not plan_path.is_file():
            self.skipTest("unify plan not present (clean-room test env)")
        schema = json.loads((TEMPLATES_DIR / "blueprint.schema.json")
                            .read_text())
        data = json.loads(plan_path.read_text())
        jsonschema.validate(data, schema)
        # DAG resolution
        ids = {i["id"] for i in data["items"]}
        for it in data["items"]:
            for kind, refs in (it.get("links") or {}).items():
                if isinstance(refs, list):
                    for r in refs:
                        self.assertIn(
                            r, ids,
                            f"{it['id']}.links.{kind} → {r} unresolved"
                        )


class TestPlannerSchemaInvariant(unittest.TestCase):
    """The planner schema must continue to validate against
    workflow.schema.json + maintain DAG order."""

    def test_planner_schema_validates(self):
        import jsonschema
        schema = json.loads((SCHEMAS_DIR / "workflow.schema.json").read_text())
        data = yaml.safe_load(
            (SCHEMAS_DIR / "planner" / "schema.yaml").read_text()
        )
        jsonschema.validate(data, schema)

    def test_planner_artifacts_form_acyclic_dag(self):
        data = yaml.safe_load(
            (SCHEMAS_DIR / "planner" / "schema.yaml").read_text()
        )
        ids = {a["id"] for a in data["artifacts"]}
        for a in data["artifacts"]:
            for r in a.get("requires", []):
                self.assertIn(r, ids,
                              f"{a['id']} requires unknown {r}")

    def test_planner_gate_is_create_plan(self):
        """The gate that triggers downstream is create-plan, not
        brainstorm — user's 'doesn't have to be brainstorming first'
        rule."""
        data = yaml.safe_load(
            (SCHEMAS_DIR / "planner" / "schema.yaml").read_text()
        )
        self.assertEqual(data["apply"]["gate"], "create-plan")

    def test_planner_routine_registered(self):
        """planner must be registered in workflow/routines.yaml."""
        data = yaml.safe_load(
            (SCHEMAS_DIR / "workflow" / "routines.yaml").read_text()
        )
        routines = data.get("routines", [])
        names = {r["name"] for r in routines}
        self.assertIn("planner", names,
                      "planner routine must be in routines.yaml")


class TestSubagentIsolationInvariant(unittest.TestCase):
    """Every agent that grants Bash must also declare disallowedTools
    blocking destructive ops. Catches the class of bug where an agent
    is added with broad Bash + no restriction."""

    DESTRUCTIVE_OPS = {
        "Bash(git push *)",
        "Bash(git reset *)",
        "Bash(rm *)",
    }

    def _parse_frontmatter(self, path: Path) -> dict:
        text = path.read_text()
        # Hand-parse: agent frontmatter has XML examples that break yaml.
        # We only need tools + disallowedTools lines.
        out: dict = {}
        for line in text.splitlines():
            for key in ("tools:", "disallowedTools:"):
                if line.startswith(key):
                    out[key.rstrip(":")] = line.split(":", 1)[1].strip()
                    break
        return out

    def test_every_bash_agent_has_disallowed_tools(self):
        offenders: list[str] = []
        for agent_md in sorted(AGENTS_DIR.glob("kaizen-*.md")):
            fm = self._parse_frontmatter(agent_md)
            tools = fm.get("tools", "")
            disallowed = fm.get("disallowedTools", "")
            if "Bash" not in tools:
                continue
            # Must have disallowedTools AND mention at least git push
            if not disallowed:
                offenders.append(f"{agent_md.name}: missing disallowedTools")
                continue
            # Accept either "Bash(git push *)" (specific) or "Bash(git *)"
            # (wildcard — superset that also blocks push).
            has_push_block = "git push" in disallowed or "git *" in disallowed
            if not has_push_block:
                offenders.append(
                    f"{agent_md.name}: disallowedTools missing git block "
                    f"(need Bash(git push *) or Bash(git *))"
                )
        if offenders:
            self.fail(
                "\n".join(offenders)
                + "\n\nEvery agent with Bash must declare destructive-op blocks."
            )


class TestHookWiringInvariant(unittest.TestCase):
    """The blueprint-finalize hook must stay wired in hooks.json,
    and the hook script file must exist + be executable."""

    def test_hooks_json_parses(self):
        json.loads(HOOKS_JSON.read_text())  # raises on bad json

    def test_finalize_hook_registered_on_subagentstop(self):
        hooks = json.loads(HOOKS_JSON.read_text())
        subagent_stop = hooks["hooks"]["SubagentStop"]
        commands = []
        for matcher in subagent_stop:
            for h in matcher.get("hooks", []):
                commands.append(h.get("command", ""))
        joined = " ".join(commands)
        self.assertIn("subagentstop-blueprint-finalize.sh", joined,
                      "finalize hook not wired under SubagentStop")

    def test_finalize_hook_script_exists(self):
        p = (PLUGIN_ROOT / "hooks" / "claude"
             / "subagentstop-blueprint-finalize.sh")
        self.assertTrue(p.is_file())
        # Bash syntax-check
        rc = subprocess.run(["bash", "-n", str(p)], capture_output=True)
        self.assertEqual(rc.returncode, 0,
                         f"bash -n failed: {rc.stderr.decode()}")


class TestDispatchScriptInvariant(unittest.TestCase):
    """dispatch.sh + the bin wrapper must remain syntactically valid
    + reachable."""

    def test_dispatch_script_syntax_ok(self):
        p = PLUGIN_ROOT / "scripts" / "blueprint" / "dispatch.sh"
        self.assertTrue(p.is_file())
        rc = subprocess.run(["bash", "-n", str(p)], capture_output=True)
        self.assertEqual(rc.returncode, 0,
                         f"bash -n failed: {rc.stderr.decode()}")

    def test_bin_wrapper_routes_dispatch_verb(self):
        """The bin wrapper must route `dispatch` to dispatch.sh."""
        p = PLUGIN_ROOT / "bin" / "kaizen-blueprint"
        text = p.read_text()
        self.assertIn("dispatch", text)
        self.assertIn("dispatch.sh", text)

    def test_dispatch_usage_message(self):
        """Running with no args prints usage + exits non-zero."""
        p = PLUGIN_ROOT / "scripts" / "blueprint" / "dispatch.sh"
        r = subprocess.run(["bash", str(p)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage", (r.stdout + r.stderr).lower())


class TestSmartPositionalRegression(unittest.TestCase):
    """`show 0` (numeric file arg) gets reinterpreted as items[0] of
    active plan — not as a literal filename. Catches the bug where
    argparse blindly accepted '0' as a path."""

    def test_show_numeric_argument_falls_back_to_active(self):
        import os, tempfile
        from pathlib import Path
        cli = PLUGIN_ROOT / "scripts" / "blueprint" / "blueprint.py"
        with tempfile.TemporaryDirectory() as td:
            plan = {
                "$schema": "https://kaizen-md/.../blueprint.schema.json",
                "blueprint_version": "1",
                "project": "test",
                "items": [
                    {"id": "01", "kind": "plan", "title": "Root",
                     "status": "draft", "links": {}},
                ],
            }
            plan_path = Path(td) / "plan.json"
            plan_path.write_text(json.dumps(plan))
            env = os.environ.copy()
            env["KAIZEN_BLUEPRINT_STATE"] = str(Path(td) / "state.json")
            # Populate cache first
            subprocess.run(
                ["python3", str(cli), "list", str(plan_path)],
                capture_output=True, env=env, check=True,
            )
            # Now `show 0` should pull items[0] of cached active
            r = subprocess.run(
                ["python3", str(cli), "show", "0"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["id"], "01")


if __name__ == "__main__":
    unittest.main()
