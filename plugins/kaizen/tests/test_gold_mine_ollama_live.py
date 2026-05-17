"""Live smoke tests for the gold-miner Ollama path against the
actual local granite4.1:8b model.

Skipped automatically when:
  - Ollama isn't running at http://localhost:11434
  - granite4.1:8b isn't pulled (check via `ollama list`)
  - KAIZEN_GOLD_MINE_TEST_LIVE != "1" (opt-in — keeps CI fast)

Run live: KAIZEN_GOLD_MINE_TEST_LIVE=1 KAIZEN_GOLD_MINE_ENABLE=1 \\
  python3 -m unittest tests.test_gold_mine_ollama_live -v

These tests verify the CONTRACT — does granite + the JSON-schema
format return a parseable dict with the required fields? They do
NOT assert specific score values (LLM output is non-deterministic
even at temperature=0 for small models).
"""

from __future__ import annotations

import os
import sys
import unittest
import urllib.request
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                       timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _granite_present() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                       timeout=2) as r:
            import json as _j
            data = _j.loads(r.read().decode("utf-8"))
            names = [m.get("name", "") for m in data.get("models", [])]
            return any(n.startswith("granite4.1:8b") for n in names)
    except Exception:
        return False


_LIVE_OPT_IN = os.environ.get("KAIZEN_GOLD_MINE_TEST_LIVE", "") == "1"
_REACHABLE = _ollama_reachable() if _LIVE_OPT_IN else False
_GRANITE = _granite_present() if _LIVE_OPT_IN else False

_SKIP_MSG = (
    f"live test gated: opt_in={_LIVE_OPT_IN}, "
    f"ollama_reachable={_REACHABLE}, granite_present={_GRANITE}"
)


_SCHEMA = {
    "type": "object",
    "required": ["gold_worthy", "confidence", "pattern", "tag", "reason"],
    "properties": {
        "gold_worthy": {"type": "boolean"},
        "confidence":  {"type": "number", "minimum": 0, "maximum": 1},
        "pattern":     {"type": "string"},
        "tag":         {"type": "string"},
        "reason":      {"type": "string"},
    },
}


@unittest.skipUnless(_LIVE_OPT_IN and _REACHABLE and _GRANITE, _SKIP_MSG)
class TestGraniteLive(unittest.TestCase):
    """The four live invariants we need granite to honor."""

    def setUp(self):
        # _ollama.score_hint gates on KAIZEN_GOLD_MINE_ENABLE
        self._orig_enable = os.environ.get("KAIZEN_GOLD_MINE_ENABLE")
        os.environ["KAIZEN_GOLD_MINE_ENABLE"] = "1"

    def tearDown(self):
        if self._orig_enable is None:
            os.environ.pop("KAIZEN_GOLD_MINE_ENABLE", None)
        else:
            os.environ["KAIZEN_GOLD_MINE_ENABLE"] = self._orig_enable

    def _hint(self, body: str) -> str:
        return (
            f"EVENT_TYPE: context.warn.red\n"
            f"TOOL: kaizen\n"
            f"NORMALIZED: {body}\n"
            f"RECURRENCE: 2\n"
            f"CONTEXT: PreToolUse, PostToolUse, Stop\n\n"
            f"Is this a gold-worthy developer-learning pattern worth recording?"
        )

    def test_returns_dict_with_required_fields(self):
        import _ollama
        result = _ollama.score_hint(
            self._hint("context window hit 92% — agent forgot to /compact"),
            schema=_SCHEMA, timeout=60.0,
        )
        self.assertIsNotNone(result, "live granite call returned None — see stderr")
        self.assertIsInstance(result, dict)
        for k in ("gold_worthy", "confidence", "pattern", "tag", "reason"):
            self.assertIn(k, result, f"granite response missing {k!r}: {result}")

    def test_confidence_in_unit_interval(self):
        import _ollama
        result = _ollama.score_hint(
            self._hint("repeated bash failures with same error 4 times in 30s"),
            schema=_SCHEMA, timeout=60.0,
        )
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)

    def test_gold_worthy_is_boolean(self):
        import _ollama
        result = _ollama.score_hint(
            self._hint("user typed 'hello world' as a test prompt"),
            schema=_SCHEMA, timeout=60.0,
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result["gold_worthy"], bool)

    def test_discriminates_gold_from_noise(self):
        """Smoke check that granite distinguishes obvious gold from
        obvious noise. The DISCRIMINATOR is `gold_worthy` (boolean) —
        confidence stays high for both 'definitely yes' and 'definitely
        no'. Test fails when both come back with the same gold_worthy
        verdict AND confidence within 0.1 of each other (the actual
        'model is broken' signal)."""
        import _ollama
        obvious_gold = _ollama.score_hint(
            self._hint("subprocess cwd persists across Bash tool calls — "
                        "must prefix every cd with absolute path"),
            schema=_SCHEMA, timeout=60.0,
        )
        obvious_noise = _ollama.score_hint(
            self._hint("ls returned 5 files"),
            schema=_SCHEMA, timeout=60.0,
        )
        self.assertIsNotNone(obvious_gold)
        self.assertIsNotNone(obvious_noise)
        verdict_differs = obvious_gold["gold_worthy"] != obvious_noise["gold_worthy"]
        conf_delta = abs(obvious_gold["confidence"] - obvious_noise["confidence"])
        self.assertTrue(
            verdict_differs or conf_delta >= 0.1,
            f"granite gave identical verdict for gold + noise: "
            f"gold={obvious_gold['gold_worthy']}@{obvious_gold['confidence']:.2f} "
            f"vs noise={obvious_noise['gold_worthy']}@{obvious_noise['confidence']:.2f} "
            f"(prompt + schema may be mis-calibrated)",
        )


@unittest.skipUnless(_LIVE_OPT_IN and _REACHABLE, _SKIP_MSG)
class TestModelPresenceProbe(unittest.TestCase):
    """Diagnose missing-granite case so the skip-message is useful."""

    def test_granite_is_pulled(self):
        if not _GRANITE:
            self.fail(
                "granite4.1:8b not present locally. "
                "Run: kaizen models pull granite4.1:8b"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
