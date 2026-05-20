"""Tests for scripts/blueprint/ — the 1-roundtrip plan management CLI.

Exercises the pure-core (_blueprint.py), the state cache (_state.py),
the CLI (blueprint.py), and the dispatch shell wrapper (dispatch.sh).

Run:
    python3 -m unittest tests.test_blueprint_cli -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "scripts" / "blueprint"
sys.path.insert(0, str(SCRIPTS))

import _blueprint as bp  # noqa: E402
import _state as st  # noqa: E402


def _fresh_plan(items: list[dict] | None = None) -> dict:
    """Minimal valid blueprint with the items[] caller provides."""
    return {
        "$schema": "https://kaizen-md/templates/planning-blueprint/blueprint.schema.json",
        "blueprint_version": "1",
        "project": "test",
        "items": items or [],
    }


def _write_plan(tmpdir: Path, data: dict) -> Path:
    """Write a plan + return its path."""
    p = tmpdir / "plan.json"
    p.write_text(json.dumps(data, indent=2))
    return p


class TestPureRead(unittest.TestCase):
    """_blueprint.py pure-core reads."""

    def test_read_plan_returns_full_dict(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "Root",
                 "status": "draft", "links": {}},
            ]))
            plan = bp.read_plan(p)
            self.assertEqual(plan["project"], "test")
            self.assertEqual(len(plan["items"]), 1)

    def test_read_item_by_index(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
                {"id": "02", "kind": "decision", "title": "B",
                 "status": "active", "links": {}},
            ]))
            item = bp.read_item(p, index=1)
            self.assertEqual(item["id"], "02")
            self.assertEqual(item["title"], "B")

    def test_read_item_by_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
                {"id": "07", "kind": "task-list", "title": "Phase 4",
                 "status": "active", "links": {}, "tasks": []},
            ]))
            item = bp.read_item(p, id="07")
            self.assertEqual(item["kind"], "task-list")

    def test_read_item_rejects_both_args(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan())
            with self.assertRaises(ValueError):
                bp.read_item(p, index=0, id="01")

    def test_read_item_raises_keyerror_on_missing_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
            ]))
            with self.assertRaises(KeyError):
                bp.read_item(p, id="99")

    def test_list_items_compact_index(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
                {"id": "02", "kind": "decision", "title": "B",
                 "status": "active", "links": {}},
            ]))
            rows = bp.list_items(p)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["index"], 0)
            self.assertEqual(rows[1]["id"], "02")


class TestSubtree(unittest.TestCase):
    """DAG-walking read_subtree."""

    def test_subtree_follows_children(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "Root",
                 "status": "draft",
                 "links": {"children": ["02", "03"]}},
                {"id": "02", "kind": "decision", "title": "B",
                 "status": "active", "links": {"parents": ["01"]}},
                {"id": "03", "kind": "decision", "title": "C",
                 "status": "active", "links": {"parents": ["01"]}},
            ]))
            result = bp.read_subtree(p, "01", hops=1, follow="children")
            self.assertEqual(result["root"]["id"], "01")
            linked_ids = [i["id"] for i in result["linked"]]
            self.assertEqual(sorted(linked_ids), ["02", "03"])


class TestMutations(unittest.TestCase):
    """Atomic mutating helpers."""

    def test_set_item_status_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
            ]))
            result = bp.set_item_status(p, "01", "shipped")
            self.assertEqual(result, {"old": "draft", "new": "shipped"})
            # Re-read to confirm persisted
            self.assertEqual(bp.read_item(p, id="01")["status"], "shipped")

    def test_set_task_status_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "07", "kind": "task-list", "title": "L",
                 "status": "active", "links": {},
                 "tasks": [
                     {"id": "07.1", "subject": "X", "status": "pending"},
                 ]},
            ]))
            result = bp.set_task_status(p, "07.1", "completed")
            self.assertEqual(result, {"old": "pending", "new": "completed"})

    def test_add_item_rejects_duplicate_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
            ]))
            with self.assertRaises(ValueError):
                bp.add_item(p, {"id": "01", "kind": "note", "title": "dup",
                                "status": "draft", "links": {}})


class TestDagCheck(unittest.TestCase):
    """DAG resolution check."""

    def test_dag_clean_on_resolved_links(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {"children": ["02"]}},
                {"id": "02", "kind": "decision", "title": "B",
                 "status": "active", "links": {"parents": ["01"]}},
            ]))
            self.assertEqual(bp.dag_check(p), [])

    def test_dag_reports_broken_link(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {"children": ["99"]}},
            ]))
            broken = bp.dag_check(p)
            self.assertEqual(len(broken), 1)
            self.assertIn("99", broken[0])


class TestChunking(unittest.TestCase):
    """Chunking-floor rubric — default + --subagents modes."""

    def _make_list(self, n_tasks: int) -> dict:
        return _fresh_plan([
            {"id": "07", "kind": "task-list", "title": "L",
             "status": "active", "links": {},
             "tasks": [
                 {"id": f"07.{i}", "subject": f"T{i}", "status": "pending"}
                 for i in range(1, n_tasks + 1)
             ]},
        ])

    def test_default_chunks_3_tasks_each(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), self._make_list(9))
            result = bp.chunk_tasks(p, "07")  # subagents=False (default)
            self.assertEqual(result["bucket"], "PARENT_DOES_IT")
            self.assertEqual(result["n_chunks"], 3)
            for chunk in result["chunks"]:
                self.assertLessEqual(len(chunk), 3)

    def test_default_single_chunk_when_few_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), self._make_list(2))
            result = bp.chunk_tasks(p, "07")
            self.assertEqual(result["n_chunks"], 1)
            self.assertEqual(len(result["chunks"][0]), 2)

    def test_subagents_d2_rubric_parent(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), self._make_list(3))
            result = bp.chunk_tasks(p, "07", subagents=True)
            self.assertEqual(result["bucket"], "PARENT_DOES_IT")
            self.assertIsNone(result["dispatch_hint"]["agent"])

    def test_subagents_d2_rubric_one_subagent(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), self._make_list(5))
            result = bp.chunk_tasks(p, "07", subagents=True)
            self.assertEqual(result["bucket"], "ONE_SUBAGENT")
            self.assertEqual(result["dispatch_hint"]["agent"],
                             "kaizen-implementer")

    def test_subagents_d2_rubric_grid(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), self._make_list(9))
            result = bp.chunk_tasks(p, "07", subagents=True)
            self.assertEqual(result["bucket"], "GRID")
            self.assertEqual(result["dispatch_hint"]["mode"], "parallel")
            self.assertEqual(result["dispatch_hint"]["isolation"], "worktree")

    def test_subagents_skips_completed_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            plan = self._make_list(5)
            plan["items"][0]["tasks"][0]["status"] = "completed"
            plan["items"][0]["tasks"][1]["status"] = "completed"
            p = _write_plan(Path(td), plan)
            result = bp.chunk_tasks(p, "07", subagents=True)
            # 5 - 2 completed = 3 in-flight
            self.assertEqual(result["n_tasks"], 3)
            self.assertEqual(result["bucket"], "PARENT_DOES_IT")


class TestCacheState(unittest.TestCase):
    """_state.py — memory-cache state file."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_path = Path(self._tmpdir.name) / "state.json"
        os.environ["KAIZEN_BLUEPRINT_STATE"] = str(self._state_path)

    def tearDown(self):
        os.environ.pop("KAIZEN_BLUEPRINT_STATE", None)
        self._tmpdir.cleanup()

    def test_touch_populates_active(self):
        plan_dir = Path(self._tmpdir.name)
        p = _write_plan(plan_dir, _fresh_plan([
            {"id": "01", "kind": "plan", "title": "A",
             "status": "draft", "links": {}},
        ]))
        entry = st.touch(p)
        self.assertEqual(entry["n_items"], 1)
        self.assertEqual(st.get_active()["project"], "test")

    def test_cache_invalidates_on_mtime_change(self):
        plan_dir = Path(self._tmpdir.name)
        p = _write_plan(plan_dir, _fresh_plan([
            {"id": "01", "kind": "plan", "title": "A",
             "status": "draft", "links": {}},
        ]))
        st.touch(p)
        # Mutate the plan — should invalidate cache + rebuild
        import time
        time.sleep(0.01)  # ensure mtime differs
        plan = _fresh_plan([
            {"id": "01", "kind": "plan", "title": "A",
             "status": "draft", "links": {}},
            {"id": "02", "kind": "note", "title": "B",
             "status": "active", "links": {}},
        ])
        p.write_text(json.dumps(plan, indent=2))
        entry = st.touch(p)
        self.assertEqual(entry["n_items"], 2)


class TestYamlFormat(unittest.TestCase):
    """YAML blueprints — read + write round-trip via the extension switch."""

    def test_read_yaml_blueprint(self):
        import yaml
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.yaml"
            data = _fresh_plan([
                {"id": "01", "kind": "plan", "title": "Y",
                 "status": "draft", "links": {}},
            ])
            p.write_text(yaml.safe_dump(data))
            plan = bp.read_plan(p)
            self.assertEqual(plan["project"], "test")
            self.assertEqual(plan["items"][0]["id"], "01")

    def test_yaml_set_status_round_trips(self):
        import yaml
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.yaml"
            p.write_text(yaml.safe_dump(_fresh_plan([
                {"id": "01", "kind": "plan", "title": "Y",
                 "status": "draft", "links": {}},
            ])))
            bp.set_item_status(p, "01", "shipped")
            # Re-read via YAML path
            self.assertEqual(bp.read_item(p, id="01")["status"], "shipped")
            # File still parses as YAML, not JSON
            with self.assertRaises(json.JSONDecodeError):
                json.loads(p.read_text())


class TestResume(unittest.TestCase):
    """resume() — pick next actionable task."""

    def test_resume_returns_in_progress_first(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "07", "kind": "task-list", "title": "L",
                 "status": "active", "links": {},
                 "tasks": [
                     {"id": "07.1", "subject": "A", "status": "completed"},
                     {"id": "07.2", "subject": "B", "status": "in_progress"},
                     {"id": "07.3", "subject": "C", "status": "pending"},
                 ]},
            ]))
            r = bp.resume(p)
            self.assertEqual(r["task"]["id"], "07.2")

    def test_resume_skips_blocked_pending(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "07", "kind": "task-list", "title": "L",
                 "status": "active", "links": {},
                 "tasks": [
                     {"id": "07.1", "subject": "A", "status": "pending",
                      "blocked_by": ["07.2"]},
                     {"id": "07.2", "subject": "B", "status": "pending"},
                 ]},
            ]))
            r = bp.resume(p)
            # 07.1 is blocked by 07.2; 07.2 is unblocked → resume picks 07.2
            self.assertEqual(r["task"]["id"], "07.2")

    def test_resume_returns_none_when_all_done(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "07", "kind": "task-list", "title": "L",
                 "status": "shipped", "links": {},
                 "tasks": [
                     {"id": "07.1", "subject": "A", "status": "completed"},
                 ]},
            ]))
            self.assertIsNone(bp.resume(p))


class TestContentHash(unittest.TestCase):
    """Auto-injected content_hash header on every atomic write."""

    def test_hash_injected_on_mutate(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "X",
                 "status": "draft", "links": {}},
            ]))
            # First read — no stored hash yet (template doesn't have one)
            r = bp.verify_hash(p)
            self.assertTrue(r["first_read"])
            # Mutate via the CLI primitive — hash gets injected
            bp.set_item_status(p, "01", "active")
            r = bp.verify_hash(p)
            self.assertTrue(r["ok"])
            self.assertEqual(r["stored"], r["computed"])
            self.assertEqual(len(r["stored"]), 64)  # sha256 hex

    def test_hash_drift_detected(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "X",
                 "status": "draft", "links": {}},
            ]))
            bp.set_item_status(p, "01", "active")  # injects hash
            # External mutation — bypass the CLI
            raw = json.loads(p.read_text())
            raw["items"][0]["title"] = "TAMPERED"
            p.write_text(json.dumps(raw))
            # Verify catches drift
            r = bp.verify_hash(p)
            self.assertFalse(r["ok"])
            self.assertNotEqual(r["stored"], r["computed"])

    def test_hash_stable_across_rewrites(self):
        """Re-writing the same data shouldn't churn the hash."""
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "X",
                 "status": "active", "links": {}},
            ]))
            bp.set_item_status(p, "01", "active")  # no-op flip; hash injected
            h1 = bp.verify_hash(p)["computed"]
            bp.set_item_status(p, "01", "active")  # idempotent
            h2 = bp.verify_hash(p)["computed"]
            self.assertEqual(h1, h2)


class TestAutoDiscover(unittest.TestCase):
    """Fresh-session auto-discovery — single command kicks off the plan."""

    def _run(self, *args, env=None) -> tuple[int, str, str]:
        result = subprocess.run(
            ["python3", str(SCRIPTS / "blueprint.py"), *args],
            capture_output=True, text=True, timeout=15,
            env=env or os.environ.copy(),
        )
        return result.returncode, result.stdout, result.stderr

    def test_resume_in_fresh_session_finds_plan_topic_folder(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / ".kaizen" / "docs" / "2026-05-20-feature-x").mkdir(parents=True)
            plan_path = tdp / ".kaizen" / "docs" / "2026-05-20-feature-x" / "plan.json"
            plan_path.write_text(json.dumps(_fresh_plan([
                {"id": "07", "kind": "task-list", "title": "L",
                 "status": "active", "links": {},
                 "tasks": [{"id": "07.1", "subject": "go", "status": "pending"}]},
            ])))
            env = os.environ.copy()
            env["KAIZEN_BLUEPRINT_STATE"] = str(tdp / "state.json")
            # Run CLI from a subdir of the fake repo — auto-discovery should
            # walk up and find .kaizen/docs/.
            result = subprocess.run(
                ["python3", str(SCRIPTS / "blueprint.py"), "resume"],
                cwd=str(tdp), env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("07.1", result.stdout)

    def test_auto_discover_prefers_plan_over_blueprint(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # Create both — a brainstorm-bundle blueprint AND a workflow plan
            (tdp / ".kaizen" / "docs" / "2026-05-19-brainstorm").mkdir(parents=True)
            (tdp / ".kaizen" / "docs" / "2026-05-20-master").mkdir(parents=True)
            (tdp / ".kaizen" / "docs" / "2026-05-19-brainstorm" / "blueprint.json").write_text(
                json.dumps(_fresh_plan([
                    {"id": "01", "kind": "brainstorm", "title": "BS",
                     "status": "shipped", "links": {}}
                ])))
            (tdp / ".kaizen" / "docs" / "2026-05-20-master" / "plan.json").write_text(
                json.dumps(_fresh_plan([
                    {"id": "01", "kind": "plan", "title": "Master",
                     "status": "active", "links": {}}
                ])))
            env = os.environ.copy()
            env["KAIZEN_BLUEPRINT_STATE"] = str(tdp / "state.json")
            result = subprocess.run(
                ["python3", str(SCRIPTS / "blueprint.py"), "state",
                 "--json"],
                cwd=str(tdp), env=env, capture_output=True, text=True,
            )
            # State alone won't trigger discovery; show triggers via _resolve_file
            result = subprocess.run(
                ["python3", str(SCRIPTS / "blueprint.py"), "show", "--id", "01"],
                cwd=str(tdp), env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Master", result.stdout)


class TestCli(unittest.TestCase):
    """End-to-end CLI smoke."""

    def _run(self, *args, env=None) -> tuple[int, str, str]:
        result = subprocess.run(
            ["python3", str(SCRIPTS / "blueprint.py"), *args],
            capture_output=True, text=True, timeout=15,
            env=env or os.environ.copy(),
        )
        return result.returncode, result.stdout, result.stderr

    def _isolated_env(self, state_path: Path) -> dict:
        env = os.environ.copy()
        env["KAIZEN_BLUEPRINT_STATE"] = str(state_path)
        return env

    def test_list_command_returns_rows(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, out, err = self._run("list", str(p), env=env)
            self.assertEqual(rc, 0, err)
            self.assertIn("01", out)
            self.assertIn("plan", out)

    def test_show_by_index_returns_one_item(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
                {"id": "02", "kind": "decision", "title": "B",
                 "status": "active", "links": {}},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, out, _ = self._run("show", str(p), "1", env=env)
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["id"], "02")

    def test_set_status_persists(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "A",
                 "status": "draft", "links": {}},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, _, err = self._run(
                "set-status", str(p), "--id", "01", "--status", "shipped",
                env=env)
            self.assertEqual(rc, 0, err)
            data = json.loads(p.read_text())
            self.assertEqual(data["items"][0]["status"], "shipped")

    def test_add_item_auto_picks_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "Root",
                 "status": "draft", "links": {}},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, out, err = self._run(
                "add-item", str(p), "--kind", "decision",
                "--title", "Pick the storage", env=env)
            self.assertEqual(rc, 0, err)
            self.assertIn("02", out)  # next free id after 01
            data = json.loads(p.read_text())
            self.assertEqual(len(data["items"]), 2)
            self.assertEqual(data["items"][1]["id"], "02")
            self.assertEqual(data["items"][1]["kind"], "decision")

    def test_add_item_auto_links_parent_children(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "Root",
                 "status": "draft",
                 "links": {"children": [], "parents": [],
                           "related": [], "supersedes": [],
                           "superseded_by": None}},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, _, err = self._run(
                "add-item", str(p), "--kind", "note",
                "--title", "Side note", "--parent", "01", env=env)
            self.assertEqual(rc, 0, err)
            data = json.loads(p.read_text())
            self.assertIn("02", data["items"][0]["links"]["children"])
            self.assertIn("01", data["items"][1]["links"]["parents"])

    def test_add_task_auto_picks_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "07", "kind": "task-list", "title": "Phase X",
                 "status": "active", "links": {},
                 "tasks": [
                     {"id": "07.1", "subject": "first", "status": "pending"},
                 ]},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, out, err = self._run(
                "add-task", str(p), "--to", "07",
                "--subject", "second task", env=env)
            self.assertEqual(rc, 0, err)
            self.assertIn("07.2", out)
            data = json.loads(p.read_text())
            self.assertEqual(data["items"][0]["tasks"][1]["id"], "07.2")

    def test_add_task_rejects_non_task_list(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "01", "kind": "plan", "title": "R",
                 "status": "draft", "links": {}},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, _, err = self._run(
                "add-task", str(p), "--to", "01",
                "--subject", "x", env=env)
            self.assertNotEqual(rc, 0)
            self.assertIn("task-list", err)

    def test_chunk_command_runs(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_plan(Path(td), _fresh_plan([
                {"id": "07", "kind": "task-list", "title": "L",
                 "status": "active", "links": {},
                 "tasks": [
                     {"id": f"07.{i}", "subject": f"T{i}",
                      "status": "pending"} for i in range(1, 8)
                 ]},
            ]))
            env = self._isolated_env(Path(td) / "state.json")
            rc, out, err = self._run(
                "chunk", str(p), "--list-id", "07", "--json", env=env)
            self.assertEqual(rc, 0, err)
            data = json.loads(out)
            self.assertEqual(data["n_tasks"], 7)
            self.assertEqual(data["bucket"], "PARENT_DOES_IT")


if __name__ == "__main__":
    unittest.main()
