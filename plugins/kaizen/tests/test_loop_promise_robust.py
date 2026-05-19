"""Regression + feature tests for the 2026-05-14 promise-robustness fixes.

Three improvements to ralph-loop completion semantics:

1. **Fence-aware text-promise matching** (check_completion_promise) —
   strips markdown code fences and requires the promise tag at MESSAGE
   END before triggering completion. Prevents the false positive that
   ended the 2026-05-14 loop from a `<promise>DONE</promise>` token
   embedded in an Iron-Law explanation.

2. **Structured loop_promise() tool** (emit_promise) — writes phrase to
   `last_promise:` frontmatter field. Tool calls can't be confused with
   text content.

3. **File-path auto-load in setup script** — `/kaizen:loop handoff.md`
   reads the file's contents as the prompt body instead of using the
   literal filename string.

Run:
    python3 -m unittest tests.test_loop_promise_robust -v
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
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))

import loop_ledger as ll  # noqa: E402
import loop_state as ls  # noqa: E402


SETUP_SCRIPT = PLUGIN_ROOT / "skills" / "loop" / "scripts" / "setup-ralph-loop.sh"
HOOK_CC = PLUGIN_ROOT / "hooks" / "claude" / "stop-ralph.sh"


# ─── 1. check_completion_promise — fence-aware end-of-message matching ─


class TestCheckCompletionPromise(unittest.TestCase):
    def test_promise_at_message_end_matches(self):
        msg = "All work complete.\n\n<promise>DONE</promise>"
        self.assertTrue(ll.check_completion_promise(msg, "DONE"))

    def test_promise_at_message_end_with_trailing_whitespace(self):
        msg = "All done.\n<promise>DONE</promise>\n\n  \n"
        self.assertTrue(ll.check_completion_promise(msg, "DONE"))

    def test_promise_in_middle_does_not_match(self):
        """The 2026-05-14 regression: agent mentions the promise in
        explanatory text but follows it with more content."""
        msg = (
            "The completion phrase is <promise>DONE</promise>. "
            "Don't emit it until criteria are met. Now let me show you a fix..."
        )
        self.assertFalse(ll.check_completion_promise(msg, "DONE"))

    def test_promise_inside_fenced_code_does_not_match(self):
        """The exact scenario that ended the prior loop: code-fence example."""
        msg = (
            "## Iron Laws\n\n"
            "Example of how to signal completion:\n\n"
            "```\n<promise>DONE</promise>\n```\n\n"
            "But only when truly complete."
        )
        self.assertFalse(ll.check_completion_promise(msg, "DONE"))

    def test_promise_inside_inline_code_does_not_match(self):
        msg = (
            "Set `--promise DONE` then emit `<promise>DONE</promise>` "
            "when criteria are met."
        )
        self.assertFalse(ll.check_completion_promise(msg, "DONE"))

    def test_wrong_phrase_does_not_match(self):
        msg = "Final answer.\n\n<promise>FINISHED</promise>"
        self.assertFalse(ll.check_completion_promise(msg, "DONE"))

    def test_empty_inputs(self):
        self.assertFalse(ll.check_completion_promise("", "DONE"))
        self.assertFalse(ll.check_completion_promise("text", ""))
        self.assertFalse(ll.check_completion_promise("text", "DONE"))

    def test_multiple_promise_tags_only_trailing_counts(self):
        """Agent shows an example THEN actually emits — should still match."""
        msg = (
            "Example: when you'd write `<promise>DONE</promise>` to signal.\n\n"
            "I've now met all criteria.\n\n<promise>DONE</promise>"
        )
        self.assertTrue(ll.check_completion_promise(msg, "DONE"))

    def test_collapses_inner_whitespace(self):
        """Promise with newlines/whitespace inside the tag still matches."""
        msg = "ok\n\n<promise>\n  DONE\n  </promise>"
        self.assertTrue(ll.check_completion_promise(msg, "DONE"))


class TestHasUnsafePromiseMention(unittest.TestCase):
    """Diagnostic helper for surfacing why a loop didn't end despite mentions."""

    def test_unsafe_when_mention_not_at_end(self):
        msg = "Use <promise>DONE</promise> to signal. More text follows."
        self.assertTrue(ll.has_unsafe_promise_mention(msg))

    def test_safe_when_at_end(self):
        msg = "All done.\n<promise>DONE</promise>"
        self.assertFalse(ll.has_unsafe_promise_mention(msg))

    def test_safe_when_in_code_fence(self):
        msg = "```\n<promise>X</promise>\n```\n"
        self.assertFalse(
            ll.has_unsafe_promise_mention(msg),
            "tags inside code fences should not trigger the diagnostic"
        )

    def test_no_mention_no_diagnostic(self):
        self.assertFalse(ll.has_unsafe_promise_mention("plain text"))


# ─── 2. promise-check CLI subcommand ─────────────────────────────────


class TestPromiseCheckCLI(unittest.TestCase):
    HELPER = PLUGIN_ROOT / "scripts" / "state" / "loop_ledger.py"

    def _run(self, body: str, phrase: str) -> int:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as fh:
            fh.write(body)
            path = fh.name
        try:
            result = subprocess.run(
                ["python3", str(self.HELPER), "promise-check", path, phrase],
                capture_output=True, text=True,
            )
            return result.returncode
        finally:
            os.unlink(path)

    def test_exit_zero_when_promise_at_end(self):
        self.assertEqual(self._run("all done\n<promise>DONE</promise>", "DONE"), 0)

    def test_exit_one_when_promise_in_code_fence(self):
        self.assertEqual(
            self._run("```\n<promise>DONE</promise>\n```\nmore", "DONE"), 1
        )

    def test_exit_one_when_no_promise(self):
        self.assertEqual(self._run("just words", "DONE"), 1)


# ─── 3. emit_promise — structured tool path ──────────────────────────


class _CwdMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpcm.cleanup()


def _init_loop(tmpdir: Path, **flags):
    args = ["bash", str(SETUP_SCRIPT)]
    for k, v in flags.items():
        args.extend([f"--{k.replace('_', '-')}", str(v)])
    args.append("seed prompt")
    subprocess.run(args, cwd=tmpdir, check=True, capture_output=True)


class TestEmitPromise(_CwdMixin, unittest.TestCase):
    def test_writes_last_promise_field(self):
        _init_loop(self.tmp, promise="DONE", its=5)
        result = ls.emit_promise("DONE")
        self.assertTrue(result["emitted"])
        self.assertTrue(result["matches"])
        state = (self.tmp / ".kaizen" / "loop.state.md").read_text()
        self.assertIn('last_promise: "DONE"', state)

    def test_reports_mismatch_when_phrase_differs(self):
        _init_loop(self.tmp, promise="DONE", its=5)
        result = ls.emit_promise("WRONG")
        self.assertTrue(result["emitted"])
        self.assertFalse(result["matches"])
        self.assertEqual(result["configured_promise"], "DONE")

    def test_empty_phrase_raises(self):
        _init_loop(self.tmp, promise="DONE", its=5)
        with self.assertRaises(ValueError):
            ls.emit_promise("")

    def test_missing_loop_raises_filenotfound(self):
        # No setup — no state file
        with self.assertRaises(FileNotFoundError):
            ls.emit_promise("DONE")

    def test_replacing_prior_promise(self):
        _init_loop(self.tmp, promise="DONE", its=5)
        ls.emit_promise("ATTEMPT1")
        ls.emit_promise("DONE")
        state = (self.tmp / ".kaizen" / "loop.state.md").read_text()
        # Only one last_promise line; final value is the most recent
        self.assertEqual(state.count("last_promise:"), 1)
        self.assertIn('last_promise: "DONE"', state)


class TestEmitPromiseCLI(_CwdMixin, unittest.TestCase):
    HELPER = PLUGIN_ROOT / "scripts" / "state" / "loop_state.py"

    def test_promise_subcommand_writes_field(self):
        _init_loop(self.tmp, promise="DONE", its=5)
        result = subprocess.run(
            ["python3", str(self.HELPER), "promise", "DONE"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = (self.tmp / ".kaizen" / "loop.state.md").read_text()
        self.assertIn('last_promise: "DONE"', state)


# ─── 4. File-path auto-load in setup script ──────────────────────────


class TestSetupFilePathAutoLoad(unittest.TestCase):
    def test_existing_file_path_loads_contents(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger_doc = tmp / "myplan.md"
            ledger_doc.write_text(
                "# My plan\n\nDo step A, then B, then output <promise>DONE</promise>.\n"
            )
            result = subprocess.run(
                ["bash", str(SETUP_SCRIPT), str(ledger_doc),
                 "--its", "5", "--promise", "DONE"],
                cwd=tmp, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            # Body should contain the file's contents, NOT the filename
            self.assertIn("# My plan", state)
            self.assertIn("Do step A", state)
            # The literal filename should not appear in the body
            body_only = state.split("---\n", 2)[-1]
            self.assertNotIn(str(ledger_doc), body_only)

    def test_non_existing_string_used_literally(self):
        """Backward-compat: a multi-word prompt or a non-file string is
        used as the literal prompt body (the historical behavior)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "build", "a", "thing",
                 "--its", "5"],
                cwd=tmp, check=True, capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            self.assertEqual(body, "build a thing")

    def test_multi_word_prompt_not_auto_loaded(self):
        """If the prompt is more than one token (even if one happens to be
        a file path), don't auto-load — the user clearly intended prose."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            doc = tmp / "plan.md"
            doc.write_text("file contents")
            subprocess.run(
                ["bash", str(SETUP_SCRIPT),
                 "read", "and", "run", str(doc), "--its", "5"],
                cwd=tmp, check=True, capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            self.assertIn("read and run", body)
            self.assertIn(str(doc), body)
            self.assertNotIn("file contents", body)


# ─── 5. End-to-end via the bash hook ─────────────────────────────────


class TestHookHonorsStructuredPromise(unittest.TestCase):
    """The Stop hook should end the loop when last_promise matches,
    BEFORE the text-regex fallback."""

    def test_hook_ends_loop_on_structured_promise(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / ".kaizen"
            state_dir.mkdir()
            (state_dir / "loop.state.md").write_text(
                '---\n'
                'active: true\n'
                'iteration: 1\n'
                'session_id: ""\n'
                'last_turn_id: ""\n'
                'max_iterations: 10\n'
                'completion_promise: "DONE"\n'
                'last_promise: "DONE"\n'  # structured signal
                'started_at: "2026-05-13T00:00:00Z"\n'
                '---\n'
                'still pending work\n'
            )
            result = subprocess.run(
                ["bash", str(HOOK_CC)],
                input=json.dumps({
                    "cwd": td, "session_id": "any", "turn_id": "t1",
                    "last_assistant_message": "no promise here at all",
                }),
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["continue"], False)
            self.assertIn("structured promise", payload["stopReason"].lower())
            self.assertFalse((state_dir / "loop.state.md").is_file())

    def test_hook_does_not_end_on_fenced_promise_text(self):
        """Regression check: the 2026-05-14 false-positive scenario."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / ".kaizen"
            state_dir.mkdir()
            (state_dir / "loop.state.md").write_text(
                '---\n'
                'active: true\n'
                'iteration: 1\n'
                'session_id: ""\n'
                'last_turn_id: ""\n'
                'max_iterations: 10\n'
                'completion_promise: "DONE"\n'
                'started_at: "2026-05-13T00:00:00Z"\n'
                '---\n'
                'still working\n'
            )
            msg = (
                "Working through items.\n\n"
                "## Iron Law\n\n"
                "When done, emit:\n\n"
                "```\n<promise>DONE</promise>\n```\n\n"
                "But criteria are not yet met."
            )
            result = subprocess.run(
                ["bash", str(HOOK_CC)],
                input=json.dumps({
                    "cwd": td, "session_id": "any", "turn_id": "t1",
                    "last_assistant_message": msg,
                }),
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            # Should NOT end — loop continues via decision: block
            self.assertEqual(payload.get("decision"), "block")


if __name__ == "__main__":
    unittest.main()
