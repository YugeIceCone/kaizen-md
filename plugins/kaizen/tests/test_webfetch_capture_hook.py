"""Tests for hooks/claude/posttool-webfetch-capture.sh.

PostToolUse hook with matcher=WebFetch. Captures fetched docs to
~/.claude/.kaizen/web-fetches.jsonl for later semantic recall (future
kaizen-knowledge corpus). Observability-only; never blocks.

Sandbox: KAIZEN_WEBFETCH_CAPTURE_LOG redirects the output file.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HOOK = ROOT / "hooks/claude/posttool-webfetch-capture.sh"


def _run_hook(payload: dict, env_extra: dict | None = None):
    env = os.environ.copy()
    env["KAIZEN_TRACE_DISABLE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5, env=env,
    )


class TestHookSmoke(unittest.TestCase):

    def test_present_and_executable(self):
        self.assertTrue(_HOOK.is_file(), f"missing: {_HOOK}")
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_exits_zero_on_empty(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            r = subprocess.run(
                ["bash", str(_HOOK)], input="",
                capture_output=True, text=True, timeout=5,
                env={**os.environ, "KAIZEN_TRACE_DISABLE": "1",
                     "KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)},
            )
        self.assertEqual(r.returncode, 0)


class TestCapture(unittest.TestCase):

    def test_captures_webfetch_response(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            payload = {
                "session_id": "sid-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "WebFetch",
                "tool_input": {
                    "url": "https://example.com/docs",
                    "prompt": "Extract API surface.",
                },
                "tool_response": {
                    "content": "GET /api/v1 — returns user info.",
                },
            }
            _run_hook(payload, {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)})
            entry = json.loads(log.read_text().strip())
            self.assertEqual(entry["url"], "https://example.com/docs")
            self.assertEqual(entry["prompt"], "Extract API surface.")
            self.assertIn("user info", entry["response"])
            self.assertEqual(entry["session_id"], "sid-1")
            self.assertEqual(entry["tool"], "WebFetch")
            self.assertIn("ts", entry)

    def test_truncates_oversized_response(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            big_body = "x" * 50_000
            payload = {
                "session_id": "s", "tool_name": "WebFetch",
                "tool_input": {"url": "u", "prompt": "p"},
                "tool_response": {"content": big_body},
            }
            _run_hook(payload, {
                "KAIZEN_WEBFETCH_CAPTURE_LOG": str(log),
                "KAIZEN_WEBFETCH_CAPTURE_MAX_BYTES": "1000",
            })
            entry = json.loads(log.read_text().strip())
            # Body trimmed to 1000B + the truncation marker
            self.assertLessEqual(len(entry["response"]), 1100)
            self.assertIn("truncated", entry["response"])

    def test_skips_non_webfetch_tools(self):
        """Defense-in-depth: even if matcher misroutes, the hook
        ignores non-WebFetch tools (e.g. Bash, Read)."""
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "tool_response": {"content": "foo\nbar\n"},
            }
            _run_hook(payload, {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)})
            self.assertFalse(log.exists(),
                "non-WebFetch tools must not land in the capture log")

    def test_captures_context7_doc_queries(self):
        """Sister surface: MCP Context7 doc-queries are also valuable
        fetches and use the same shape."""
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            payload = {
                "tool_name": "mcp__claude_ai_Context7__query-docs",
                "tool_input": {"url": "<library>", "prompt": "X"},
                "tool_response": {"content": "doc body"},
            }
            _run_hook(payload, {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)})
            entry = json.loads(log.read_text().strip())
            self.assertEqual(entry["tool"],
                             "mcp__claude_ai_Context7__query-docs")


class TestDisableAndSafety(unittest.TestCase):

    def test_disable_env_suppresses(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            payload = {
                "tool_name": "WebFetch",
                "tool_input": {"url": "u", "prompt": "p"},
                "tool_response": {"content": "body"},
            }
            _run_hook(payload, {
                "KAIZEN_WEBFETCH_CAPTURE_LOG": str(log),
                "KAIZEN_WEBFETCH_CAPTURE_DISABLE": "1",
            })
            self.assertFalse(log.exists())

    def test_malformed_json_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            r = subprocess.run(
                ["bash", str(_HOOK)],
                input="{{{not json",
                capture_output=True, text=True, timeout=5,
                env={**os.environ, "KAIZEN_TRACE_DISABLE": "1",
                     "KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)},
            )
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
