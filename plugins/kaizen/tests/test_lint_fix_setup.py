"""RED first — local-LLM detection + setup.

Two surfaces:
  detect_servers()       → list[dict] of reachable OpenAI-compatible
                           endpoints (sweep candidate ports: 11434
                           ollama, 8080 llama-server, custom from env).
                           Each entry: {url, kind, models, reachable}.
  generate_install_script(target: str) → str
                           Returns a bash script that installs the
                           named target ('ollama' | 'llama-server')
                           and starts it. Does NOT run anything itself.
  setup_summary(repo_root) → dict
                           Top-level orchestrator: detect + summarise
                           what action the caller should take next.

Run:
    python3 -m unittest tests.test_lint_fix_setup -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))

import lint_fix_setup as setup  # noqa: E402


class DetectServers(unittest.TestCase):

    def test_all_candidates_unreachable_returns_empty_list(self):
        with mock.patch.object(setup, "_probe", autospec=True) as p:
            p.return_value = None
            out = setup.detect_servers()
            self.assertEqual(out, [])
            self.assertGreater(p.call_count, 0)   # actually swept

    def test_detects_reachable_ollama(self):
        with mock.patch.object(setup, "_probe", autospec=True) as p:
            p.side_effect = lambda url, timeout=1.0: (
                {"object": "list", "data": [{"id": "qwen2.5-coder:1.5b"}]}
                if "11434" in url else None
            )
            out = setup.detect_servers()
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["kind"], "ollama")
            self.assertIn("qwen2.5-coder:1.5b",
                          [m["id"] for m in out[0]["models"]])

    def test_detects_reachable_llama_server(self):
        with mock.patch.object(setup, "_probe", autospec=True) as p:
            p.side_effect = lambda url, timeout=1.0: (
                {"object": "list", "data": [{"id": "local"}]}
                if "8080" in url else None
            )
            out = setup.detect_servers()
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["kind"], "llama-server")

    def test_detect_includes_llm_base_url_env_when_set(self):
        with mock.patch.dict("os.environ", {"LLM_BASE_URL": "http://127.0.0.1:9999"}):
            with mock.patch.object(setup, "_probe", autospec=True) as p:
                p.side_effect = lambda url, timeout=1.0: (
                    {"object": "list", "data": []} if "9999" in url else None
                )
                out = setup.detect_servers()
                self.assertEqual(len(out), 1)
                self.assertEqual(out[0]["url"], "http://127.0.0.1:9999")


class InstallScript(unittest.TestCase):

    def test_generate_install_script_returns_bash_for_ollama(self):
        script = setup.generate_install_script("ollama")
        self.assertTrue(script.startswith("#!/usr/bin/env bash"))
        self.assertIn("ollama", script.lower())
        # Pulls a small coder model
        self.assertIn("ollama pull", script)

    def test_generate_install_script_returns_bash_for_llama_server(self):
        script = setup.generate_install_script("llama-server")
        self.assertTrue(script.startswith("#!/usr/bin/env bash"))
        self.assertIn("llama-server", script.lower())

    def test_generate_install_script_rejects_unknown_target(self):
        with self.assertRaises(ValueError):
            setup.generate_install_script("not-a-real-target")

    def test_install_script_uses_set_e_for_error_propagation(self):
        script = setup.generate_install_script("ollama")
        # Either `set -e` or `set -euo pipefail` — both acceptable
        self.assertTrue("set -e" in script or "set -euo" in script)


class InstallScriptOutput(unittest.TestCase):
    """Pin the post-install output guarantees so we don't regress to the
    1000-line ollama TTY-redraw spam the early version emitted."""

    def test_ollama_script_strips_tty_redraws(self):
        """Either pipes through `tr -d` to strip control chars, or sets
        an env var that disables ollama's spinner. Either way, the
        script must not propagate raw `\\x1b[?25l` sequences when stdout
        isn't a TTY."""
        s = setup.generate_install_script("ollama")
        self.assertTrue(
            "OLLAMA_NOPROGRESS" in s or "tr -d" in s or "stdbuf" in s
            or "[:cntrl:]" in s or "--no-tty" in s,
            "ollama pull must be wrapped to suppress TTY redraws when "
            "stdout is not a terminal — found neither env-var nor pipe",
        )

    def test_ollama_script_prints_bordered_summary(self):
        s = setup.generate_install_script("ollama")
        # Box-drawing chars OR a clear marker the user can spot
        self.assertTrue(
            "═" in s or "===" in s or "─" in s,
            "post-install summary should be visually framed",
        )

    def test_ollama_script_contains_self_verifying_curl(self):
        s = setup.generate_install_script("ollama")
        # Final smoke test — the script should hit /v1/models and report
        self.assertIn("/v1/models", s)
        self.assertIn("curl", s)
        # The verification check should be near the END of the script
        # (so the user sees ✓/✗ as the last thing)
        idx_verify = s.rfind("/v1/models")
        self.assertGreater(idx_verify, len(s) * 0.5,
                            "verification curl should be in the latter half")

    def test_ollama_script_surfaces_export_commands_at_end(self):
        s = setup.generate_install_script("ollama")
        self.assertIn("export LLM_BASE_URL=http://127.0.0.1:11434", s)
        self.assertIn("export LLM_MODEL=", s)

    def test_ollama_script_prints_next_step_with_auto_fix_lint(self):
        """Caller should see how to actually USE the LLM once installed."""
        s = setup.generate_install_script("ollama")
        self.assertIn("auto_fix_lint", s)


class StartIdle(unittest.TestCase):

    def test_start_ollama_skips_when_already_running(self):
        """If detect_servers() finds an ollama already, start is a no-op."""
        with mock.patch.object(setup, "detect_servers", autospec=True) as ds:
            ds.return_value = [{"url": "http://127.0.0.1:11434", "kind": "ollama",
                                 "models": [], "reachable": True}]
            with mock.patch.object(setup, "_spawn_background", autospec=True) as sp:
                out = setup.start_ollama_if_idle()
                sp.assert_not_called()
                self.assertEqual(out["status"], "already_running")

    def test_start_ollama_spawns_when_idle_and_binary_present(self):
        with mock.patch.object(setup, "detect_servers", autospec=True) as ds:
            ds.return_value = []
            with mock.patch.object(setup, "_which", autospec=True) as w:
                w.return_value = "/usr/local/bin/ollama"
                with mock.patch.object(setup, "_spawn_background",
                                        autospec=True) as sp:
                    sp.return_value = 12345   # pid
                    out = setup.start_ollama_if_idle()
                    sp.assert_called_once()
                    self.assertEqual(out["status"], "started")
                    self.assertEqual(out["pid"], 12345)

    def test_start_ollama_returns_not_installed_when_binary_missing(self):
        with mock.patch.object(setup, "detect_servers", autospec=True) as ds:
            ds.return_value = []
            with mock.patch.object(setup, "_which", autospec=True) as w:
                w.return_value = None
                out = setup.start_ollama_if_idle()
                self.assertEqual(out["status"], "not_installed")
                # Surfaces the install script for the caller
                self.assertIn("install_script", out)
                self.assertTrue(out["install_script"].startswith("#!/usr/bin/env bash"))


class SetupSummary(unittest.TestCase):

    def test_setup_summary_reachable_path(self):
        with mock.patch.object(setup, "detect_servers", autospec=True) as ds:
            ds.return_value = [{"url": "http://127.0.0.1:11434", "kind": "ollama",
                                 "models": [{"id": "qwen2.5-coder"}], "reachable": True}]
            out = setup.setup_summary()
            self.assertEqual(out["status"], "ready")
            self.assertEqual(out["recommended_url"], "http://127.0.0.1:11434")
            self.assertEqual(out["recommended_model"], "qwen2.5-coder")

    def test_setup_summary_unreachable_offers_install(self):
        with mock.patch.object(setup, "detect_servers", autospec=True) as ds:
            ds.return_value = []
            out = setup.setup_summary()
            self.assertEqual(out["status"], "setup_needed")
            self.assertIn("install_script", out)
            self.assertIn("setup_command", out)   # one-liner the user can run

    def test_setup_summary_companion_shell_script_exists(self):
        """The standalone setup-local-llm.sh ships alongside the Python
        module so users can run it without the MCP tool."""
        script = (PLUGIN_ROOT / "skills" / "workflow" / "scripts" /
                  "setup-local-llm.sh")
        self.assertTrue(script.exists(), f"missing: {script}")


if __name__ == "__main__":
    unittest.main()
