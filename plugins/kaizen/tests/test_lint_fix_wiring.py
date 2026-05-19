"""RED first — wiring tests: dispatch + auto_fix_lint honor prefs;
the new lint_fix_setup_local_llm MCP tool returns the structured spec.

These are the integration-level tests for the prefs + setup feature.

Run:
    python3 -m unittest tests.test_lint_fix_wiring -v
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "mcp"))

import lint_fix_dispatch as lfd  # noqa: E402
import lint_fix_prefs as prefs   # noqa: E402


def _findings() -> list[dict]:
    return [{
        "severity": "error", "code": "B017",
        "file": "src/foo.py", "line": 1, "col": 1,
        "message": "Do not assert blind exception", "fix_available": False,
    }]


# ─── dispatch() honors prefs when strategy="auto" ─────────────────────

class DispatchAuto(unittest.TestCase):

    def test_dispatch_auto_reads_strategy_from_prefs(self):
        with tempfile.TemporaryDirectory() as td:
            prefs.set_strategy(td, "subagent")
            out = lfd.dispatch(_findings(), strategy="auto", repo_root=td)
            self.assertEqual(out["strategy"], "subagent")

    def test_dispatch_auto_defaults_to_subagent_when_no_prefs(self):
        with tempfile.TemporaryDirectory() as td:
            out = lfd.dispatch(_findings(), strategy="auto", repo_root=td)
            self.assertEqual(out["strategy"], "subagent")

    def test_dispatch_auto_falls_back_to_subagent_when_llm_unreachable(self):
        """User picked local_llm but the server is down → degrade
        gracefully to subagent + flag the fallback."""
        with tempfile.TemporaryDirectory() as td:
            prefs.set_strategy(td, "local_llm")
            with mock.patch.object(lfd, "_local_llm_call", autospec=True):
                # Force the reachability probe to fail
                with mock.patch("lint_fix_setup.detect_servers",
                                  autospec=True) as ds:
                    ds.return_value = []
                    out = lfd.dispatch(_findings(), strategy="auto",
                                        repo_root=td)
                    self.assertEqual(out["strategy"], "subagent")
                    self.assertTrue(out.get("local_llm_fallback"))


# ─── dispatch() with explicit local_llm + unreachable → setup_needed ──

class DispatchSetupNeeded(unittest.TestCase):

    def test_explicit_local_llm_unreachable_returns_setup_needed(self):
        """Explicit strategy='local_llm' but no server → caller deserves
        the setup spec instead of an opaque HTTP error."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("lint_fix_setup.detect_servers",
                              autospec=True) as ds:
                ds.return_value = []
                out = lfd.dispatch(_findings(), strategy="local_llm",
                                    repo_root=td)
                self.assertEqual(out.get("status"), "setup_needed")
                self.assertIn("install_script", out)


# ─── auto_fix_lint wires through to dispatch + prefs ─────────────────

class AutoFixLintWiring(unittest.TestCase):

    def test_auto_fix_lint_persists_strategy_when_remember_true(self):
        """auto_fix_lint(..., remember_choice=True) writes the prefs
        file so the next invocation honors it."""
        # Import inside test so module-level import side effects don't bleed
        import importlib
        sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
        lint_mcp = importlib.import_module("lint_mcp")
        importlib.reload(lint_mcp)

        with tempfile.TemporaryDirectory() as td:
            # Stub the upstream linters so we don't actually run ruff/ty
            async def _stub_ruff(**_kw):
                return {"findings": _findings()}
            async def _stub_ty(**_kw):
                return {"findings": []}

            with mock.patch.object(lint_mcp, "ruff_check", _stub_ruff), \
                 mock.patch.object(lint_mcp, "ty_check", _stub_ty), \
                 mock.patch.object(lint_mcp, "_repo_root", return_value=td):

                out = asyncio.run(lint_mcp.auto_fix_lint(
                    path=td, strategy="subagent",
                    remember_choice=True,
                ))
                self.assertEqual(out["strategy"], "subagent")
                self.assertEqual(prefs.get_strategy(td), "subagent")


# ─── lint_fix_setup_local_llm MCP tool surface ───────────────────────

class SetupToolSurface(unittest.TestCase):

    def test_lint_fix_setup_local_llm_returns_summary(self):
        import importlib
        sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
        lint_mcp = importlib.import_module("lint_mcp")
        importlib.reload(lint_mcp)

        with mock.patch("lint_fix_setup.detect_servers",
                          autospec=True) as ds:
            ds.return_value = [{
                "url": "http://127.0.0.1:11434", "kind": "ollama",
                "models": [{"id": "qwen2.5-coder"}], "reachable": True,
            }]
            out = asyncio.run(lint_mcp.lint_fix_setup_local_llm())
            self.assertEqual(out["status"], "ready")
            self.assertEqual(out["recommended_url"], "http://127.0.0.1:11434")

    def test_lint_fix_setup_local_llm_offers_install_when_idle(self):
        import importlib
        sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
        lint_mcp = importlib.import_module("lint_mcp")
        importlib.reload(lint_mcp)

        with mock.patch("lint_fix_setup.detect_servers",
                          autospec=True) as ds:
            ds.return_value = []
            out = asyncio.run(lint_mcp.lint_fix_setup_local_llm())
            self.assertEqual(out["status"], "setup_needed")
            self.assertIn("install_script", out)
            self.assertIn("setup_command", out)


if __name__ == "__main__":
    unittest.main()
