"""Tests for E7 + E8 — embedding-runtime knobs.

E7 — KAIZEN_EMBED_MP_WORKERS / KAIZEN_EMBED_MP_THRESHOLD env vars gate
multi-process encoding for large batches. E8 — KAIZEN_EMBED_NORMALIZE
toggles the extra L2 normalize pass.

These tests verify the CONFIG helpers without spinning up real models
(sentence-transformers is heavyweight). Behavior under live model calls
is exercised by the integration test in test_onboard_*.

Run:
    python3 -m unittest tests.test_embed_runtime_knobs -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import _embed as kz_embed  # noqa: E402

class _EnvSandbox:
    """Save/restore relevant env vars between tests."""

    KEYS = (
        "KAIZEN_EMBED_MP_WORKERS",
        "KAIZEN_EMBED_MP_THRESHOLD",
        "KAIZEN_EMBED_NORMALIZE",
    )

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        return self

    def __exit__(self, *_):
        for k in self.KEYS:
            v = self._saved.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

# ─── E7 — multi-process workers + threshold ──────────────────────────

class TestMultiProcessWorkersConfig(unittest.TestCase):
    def test_defaults_to_zero_disables_mp(self):
        with _EnvSandbox():
            self.assertEqual(kz_embed._get_mp_workers(), 0)

    def test_reads_env_var(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_WORKERS"] = "4"
            self.assertEqual(kz_embed._get_mp_workers(), 4)

    def test_clamps_negative_to_zero(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_WORKERS"] = "-3"
            self.assertEqual(kz_embed._get_mp_workers(), 0)

    def test_garbage_falls_back_to_zero(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_WORKERS"] = "not-a-number"
            self.assertEqual(kz_embed._get_mp_workers(), 0)

class TestMultiProcessThresholdConfig(unittest.TestCase):
    def test_default_is_500(self):
        with _EnvSandbox():
            self.assertEqual(kz_embed._get_mp_threshold(), 500)

    def test_reads_env_var(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_THRESHOLD"] = "100"
            self.assertEqual(kz_embed._get_mp_threshold(), 100)

    def test_garbage_falls_back_to_default(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_THRESHOLD"] = "xyz"
            self.assertEqual(kz_embed._get_mp_threshold(), 500)

class TestShouldUseMultiProcess(unittest.TestCase):
    def test_false_when_workers_zero(self):
        with _EnvSandbox():
            self.assertFalse(kz_embed._should_use_multi_process(1000))

    def test_false_when_batch_smaller_than_threshold(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_WORKERS"] = "4"
            os.environ["KAIZEN_EMBED_MP_THRESHOLD"] = "500"
            self.assertFalse(kz_embed._should_use_multi_process(100))

    def test_true_when_both_conditions_met(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_WORKERS"] = "4"
            os.environ["KAIZEN_EMBED_MP_THRESHOLD"] = "500"
            self.assertTrue(kz_embed._should_use_multi_process(1000))

    def test_exact_threshold_triggers_mp(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MP_WORKERS"] = "2"
            os.environ["KAIZEN_EMBED_MP_THRESHOLD"] = "10"
            self.assertTrue(kz_embed._should_use_multi_process(10))

# ─── E8 — normalize knob ─────────────────────────────────────────────

class TestNormalizeFlag(unittest.TestCase):
    def test_default_is_l2_true(self):
        with _EnvSandbox():
            self.assertTrue(kz_embed._get_normalize_flag())

    def test_explicit_l2_returns_true(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_NORMALIZE"] = "l2"
            self.assertTrue(kz_embed._get_normalize_flag())

    def test_none_returns_false(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_NORMALIZE"] = "none"
            self.assertFalse(kz_embed._get_normalize_flag())

    def test_case_insensitive(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_NORMALIZE"] = "L2"
            self.assertTrue(kz_embed._get_normalize_flag())
            os.environ["KAIZEN_EMBED_NORMALIZE"] = "NONE"
            self.assertFalse(kz_embed._get_normalize_flag())

    def test_unknown_value_returns_false(self):
        """Conservative: only 'l2' enables normalize; anything else off."""
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_NORMALIZE"] = "weird"
            self.assertFalse(kz_embed._get_normalize_flag())

if __name__ == "__main__":
    unittest.main()
