"""Tests for intent_mcp.py — FastMCP server exposing kaizen-intent."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_INTENT_MCP = _KZ_DIR / "scripts/mcp" / "intent_mcp.py"


def _load_intent_mcp():
    spec = importlib.util.spec_from_file_location(
        "kaizen_intent_mcp_test", _INTENT_MCP)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {_INTENT_MCP}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kaizen_intent_mcp_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class IntentMcpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.intents_path = self.tmp / "intents.yaml"
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()
        self._orig: dict[str, str | None] = {}
        for k, v in (("KAIZEN_INTENTS_FILE", str(self.intents_path)),
                      ("KAIZEN_DXM_DIR", str(self.dxm_dir))):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        self._tmp.cleanup()
        for k, orig in self._orig.items():
            if orig is None: os.environ.pop(k, None)
            else: os.environ[k] = orig

    def _intents(self, body: str):
        self.intents_path.write_text(body, encoding="utf-8")


_SAMPLE_INTENTS = textwrap.dedent("""\
    version: 1
    intents:
      - id: wrap-up-mcp
        triggers:
          - {kind: phrase, pattern: "wrap up", case_insensitive: true}
        action: {suggest: "scaffold handoff", confidence: 0.9}
      - id: fail-pattern-mcp
        triggers:
          - kind: event_pattern
            evt_type: PostToolUse
            tool_name: Bash
            exit_code_nonzero: true
            count_at_least: 2
            window_seconds: 60
        action: {suggest: "investigate", confidence: 0.95}
""")


class TestModuleImports(unittest.TestCase):
    def test_module_loads(self):
        mod = _load_intent_mcp()
        self.assertIsNotNone(mod)

    def test_exposes_mcp_server(self):
        mod = _load_intent_mcp()
        self.assertTrue(hasattr(mod, "mcp"))


class TestRegisteredTools(unittest.TestCase):
    def _registered_names(self, mcp) -> set[str]:
        if hasattr(mcp, "list_tools"):
            tools = mcp.list_tools()
            if asyncio.iscoroutine(tools):
                tools = asyncio.run(tools)
            return {t.name if hasattr(t, "name") else str(t) for t in tools}
        return set()

    def test_expected_tools_registered(self):
        mod = _load_intent_mcp()
        registered = self._registered_names(mod.mcp)
        expected = {"intent_list", "intent_match", "intent_suggest", "intent_scan"}
        missing = expected - registered
        self.assertFalse(missing,
                          f"missing tools: {missing}; registered: {registered}")


class TestIntentListTool(IntentMcpBase):
    def test_intent_list_returns_intents(self):
        self._intents(_SAMPLE_INTENTS)
        mod = _load_intent_mcp()
        result = asyncio.run(mod.intent_list())
        ids = {i["id"] for i in result["intents"]}
        self.assertEqual(ids, {"wrap-up-mcp", "fail-pattern-mcp"})


class TestIntentMatchTool(IntentMcpBase):
    def test_intent_match_phrase(self):
        self._intents(_SAMPLE_INTENTS)
        mod = _load_intent_mcp()
        result = asyncio.run(mod.intent_match(text="let's wrap up now"))
        ids = {m["id"] for m in result["matched"]}
        self.assertIn("wrap-up-mcp", ids)

    def test_intent_match_events(self):
        self._intents(_SAMPLE_INTENTS)
        mod = _load_intent_mcp()
        events = [
            {"evt_type": "PostToolUse", "tool_name": "Bash",
              "exit_code": 1, "ts_unix": 100.0},
            {"evt_type": "PostToolUse", "tool_name": "Bash",
              "exit_code": 1, "ts_unix": 101.0},
        ]
        result = asyncio.run(mod.intent_match(events=events))
        ids = {m["id"] for m in result["matched"]}
        self.assertIn("fail-pattern-mcp", ids)


class TestIntentSuggestTool(IntentMcpBase):
    def test_intent_suggest_returns_top_match(self):
        self._intents(_SAMPLE_INTENTS)
        mod = _load_intent_mcp()
        result = asyncio.run(mod.intent_suggest(text="wrap up please"))
        self.assertIsNotNone(result.get("intent"))
        self.assertEqual(result["intent"]["id"], "wrap-up-mcp")

    def test_intent_suggest_no_match_returns_null(self):
        self._intents(_SAMPLE_INTENTS)
        mod = _load_intent_mcp()
        result = asyncio.run(mod.intent_suggest(text="completely unrelated"))
        self.assertIsNone(result.get("intent"))


class TestIntentScanTool(IntentMcpBase):
    def test_intent_scan_uses_dxm_events(self):
        self._intents(_SAMPLE_INTENTS)
        # Seed dxm with bash failures
        sys.path.insert(0, str(_SCRIPTS))
        sys.path.insert(0, str(_KZ_DIR / "scripts/mcp"))
        import dxm
        for _ in range(2):
            sub = type("A", (), {"payload": json.dumps({
                "session_id": "sess-scan-mcp",
                "evt_type": "PostToolUse",
                "tool_name": "Bash",
                "exit_code": 1}), "json": False})()
            dxm._cmd_capture(sub)
            time.sleep(0.005)
        mod = _load_intent_mcp()
        result = asyncio.run(mod.intent_scan(
            session_id="sess-scan-mcp", back_seconds=60.0))
        ids = {m["id"] for m in result["matched"]}
        self.assertIn("fail-pattern-mcp", ids)


if __name__ == "__main__":
    unittest.main()
