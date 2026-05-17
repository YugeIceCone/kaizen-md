"""Tests for dxm_mcp.py — FastMCP server exposing deus-ex-machina tools.

Validates: module imports, tool registration, direct tool invocation
returns expected shape. Skips actual MCP-protocol roundtrip (needs
client; gateway integration covers that).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_DXM_MCP = _SCRIPTS / "dxm_mcp.py"


def _load_dxm_mcp():
    """Load dxm_mcp via explicit spec to avoid sys.path collisions
    (mirrors how gateway.py mounts it)."""
    spec = importlib.util.spec_from_file_location(
        "kaizen_dxm_mcp_test", _DXM_MCP)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {_DXM_MCP}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kaizen_dxm_mcp_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class DxmMcpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig_dxm = os.environ.get("KAIZEN_DXM_DIR")
        os.environ["KAIZEN_DXM_DIR"] = str(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig_dxm is None: os.environ.pop("KAIZEN_DXM_DIR", None)
        else: os.environ["KAIZEN_DXM_DIR"] = self._orig_dxm


# ─── module-level shape ──────────────────────────────────────────────


class TestModuleImports(unittest.TestCase):
    def test_module_loads(self):
        mod = _load_dxm_mcp()
        self.assertIsNotNone(mod)

    def test_exposes_mcp_server_object(self):
        mod = _load_dxm_mcp()
        self.assertTrue(hasattr(mod, "mcp"),
                         "dxm_mcp.py must expose a top-level `mcp` attribute "
                         "(FastMCP server) for gateway.py to mount")


# ─── tool registration ──────────────────────────────────────────────


class TestRegisteredTools(unittest.TestCase):
    """Verifies the expected tools are registered. FastMCP stores tool
    names in different attrs depending on version — we probe a couple."""

    def _registered_names(self, mcp) -> set[str]:
        # FastMCP 3.x — list_tools() returns Tool objects with .name
        if hasattr(mcp, "list_tools"):
            tools = mcp.list_tools()
            if asyncio.iscoroutine(tools):
                tools = asyncio.run(tools)
            return {t.name if hasattr(t, "name") else str(t) for t in tools}
        return set()

    def test_all_expected_tools_registered(self):
        mod = _load_dxm_mcp()
        registered = self._registered_names(mod.mcp)
        expected = {
            "dxm_now", "dxm_tail", "dxm_link", "dxm_chain",
            "dxm_session_id", "dxm_replay", "dxm_clean",
        }
        # capture intentionally NOT exposed via MCP — it's hook-only
        missing = expected - registered
        self.assertFalse(
            missing,
            f"missing MCP tools: {missing}; registered: {registered}",
        )


# ─── direct tool invocations ─────────────────────────────────────────


class TestDxmNowTool(DxmMcpBase):
    def test_dxm_now_returns_event_count(self):
        mod = _load_dxm_mcp()
        # Seed events directly via dxm.py
        sys.path.insert(0, str(_SCRIPTS))
        import dxm
        for _ in range(3):
            sub_args = type("A", (), {"payload": json.dumps({
                "session_id": "s-now-mcp", "evt_type": "PreToolUse",
                "tool_name": "Bash"}), "json": False})()
            dxm._cmd_capture(sub_args)
            time.sleep(0.005)

        result = asyncio.run(mod.dxm_now(session_id="s-now-mcp"))
        self.assertEqual(result["event_count"], 3)
        self.assertEqual(result["by_tool"].get("Bash"), 3)


class TestDxmTailTool(DxmMcpBase):
    def test_dxm_tail_respects_limit(self):
        mod = _load_dxm_mcp()
        sys.path.insert(0, str(_SCRIPTS))
        import dxm
        for i in range(5):
            sub_args = type("A", (), {"payload": json.dumps({
                "session_id": "s-tail-mcp", "evt_type": f"e{i}"}),
                "json": False})()
            dxm._cmd_capture(sub_args)
            time.sleep(0.003)
        result = asyncio.run(mod.dxm_tail(session_id="s-tail-mcp", limit=2))
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(
            [e["evt_type"] for e in result["events"]],
            ["e3", "e4"],
        )

    def test_dxm_tail_back_window(self):
        mod = _load_dxm_mcp()
        sys.path.insert(0, str(_SCRIPTS))
        import dxm
        for i in range(2):
            sub_args = type("A", (), {"payload": json.dumps({
                "session_id": "s-back-mcp", "evt_type": "old"}),
                "json": False})()
            dxm._cmd_capture(sub_args)
            time.sleep(0.005)
        time.sleep(0.3)
        sub_args = type("A", (), {"payload": json.dumps({
            "session_id": "s-back-mcp", "evt_type": "fresh"}),
            "json": False})()
        dxm._cmd_capture(sub_args)
        result = asyncio.run(mod.dxm_tail(
            session_id="s-back-mcp", back_seconds=0.2))
        self.assertEqual([e["evt_type"] for e in result["events"]], ["fresh"])


class TestDxmLinkTool(DxmMcpBase):
    def test_dxm_link_records_lineage(self):
        mod = _load_dxm_mcp()
        result = asyncio.run(mod.dxm_link(parent="P-mcp", child="C-mcp"))
        self.assertEqual(result["parent_session_id"], "P-mcp")
        self.assertEqual(result["child_session_id"], "C-mcp")
        # sessions.jsonl exists
        sessions = self.tmp / "sessions.jsonl"
        self.assertTrue(sessions.is_file())


class TestDxmChainTool(DxmMcpBase):
    def test_dxm_chain_walks_link(self):
        mod = _load_dxm_mcp()
        asyncio.run(mod.dxm_link(parent="A", child="B"))
        asyncio.run(mod.dxm_link(parent="B", child="C"))
        result = asyncio.run(mod.dxm_chain(session_id="C"))
        self.assertEqual(result["chain"], ["A", "B", "C"])
        self.assertEqual(result["depth"], 3)


class TestDxmReplayTool(DxmMcpBase):
    def test_dxm_replay_synthesizes_events(self):
        mod = _load_dxm_mcp()
        # Build a tiny fake session JSONL
        jsonl = self.tmp / "src.jsonl"
        jsonl.write_text(json.dumps({
            "type": "attachment",
            "timestamp": "2026-05-17T07:00:00.000Z",
            "sessionId": "s-replay-mcp",
            "attachment": {
                "type": "hook_success",
                "hookEvent": "PreToolUse",
                "hookName": "PreToolUse:Bash",
                "toolUseID": "toolu_test",
            },
        }) + "\n")
        result = asyncio.run(mod.dxm_replay(
            session_id="s-replay-mcp", jsonl=str(jsonl)))
        self.assertEqual(result["synthesized_count"], 1)


class TestDxmCleanTool(DxmMcpBase):
    def test_dxm_clean_dry_run(self):
        mod = _load_dxm_mcp()
        # Seed a stale file
        stale = self.tmp / "events-stale.jsonl"
        stale.write_text("{}\n")
        old_mtime = time.time() - 7 * 86400 - 60
        os.utime(stale, (old_mtime, old_mtime))
        result = asyncio.run(mod.dxm_clean(older_than="7d", dry_run=True))
        self.assertEqual(result["would_remove_count"], 1)
        # File still exists (dry run)
        self.assertTrue(stale.exists())


class TestDxmSessionIdTool(unittest.TestCase):
    """session-id needs a fake HOME with a project dir seeded."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self._orig = {"HOME": os.environ.get("HOME")}
        os.environ["HOME"] = str(self.fake_home)

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def test_session_id_discovers_latest_jsonl(self):
        mod = _load_dxm_mcp()
        cwd = self.tmp / "proj"
        cwd.mkdir()
        slug = str(cwd.resolve()).replace("/", "-")
        proj_dir = self.fake_home / ".claude" / "projects" / slug
        proj_dir.mkdir(parents=True)
        (proj_dir / "sess-mcp.jsonl").write_text("{}\n")
        result = asyncio.run(mod.dxm_session_id(cwd=str(cwd)))
        self.assertEqual(result["session_id"], "sess-mcp")


if __name__ == "__main__":
    unittest.main()
