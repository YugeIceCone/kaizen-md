"""Tests for env_overridable_dir — DRY helper extracted from 5 sites.

Per user 2026-05-18 "another round of consolidation." The shape
  def _XXX_dir() -> Path:
      env = os.environ.get("KAIZEN_XXX_DIR")
      if env:
          return Path(env)
      return Path.home() / ".claude" / ".kaizen" / "XXX"
appears in 5 modules (observer_events, _observer_capture, learning_log,
superpower_bundle x2). Per DRY rule of three+, extract.

Signature:
  env_overridable_dir(env_name, *default_segments, base=None) -> Path

  - If <env_name> is set in os.environ → Path(that value)
  - Else: base (or ~/.claude/.kaizen) joined with each default_segment
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

from _paths import env_overridable_dir  # noqa: E402

class TestEnvWins:
    def test_env_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("KAIZEN_TEST_DIR", "/tmp/sandbox-x")
        result = env_overridable_dir("KAIZEN_TEST_DIR", "default", "sub")
        assert result == Path("/tmp/sandbox-x")

    def test_empty_env_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("KAIZEN_TEST_DIR", "")
        result = env_overridable_dir("KAIZEN_TEST_DIR", "default")
        # Empty string env → fall back to default
        assert result != Path("")
        assert "default" in str(result)

class TestDefaultPath:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("KAIZEN_TEST_DIR", raising=False)
        result = env_overridable_dir("KAIZEN_TEST_DIR", "observer")
        assert result == Path.home() / ".claude" / ".kaizen" / "observer"

    def test_multiple_default_segments_joined(self, monkeypatch):
        monkeypatch.delenv("KAIZEN_TEST_DIR", raising=False)
        result = env_overridable_dir("KAIZEN_TEST_DIR",
                                       "backups", "superpowers", "patches")
        expected = Path.home() / ".claude" / ".kaizen" / "backups" / "superpowers" / "patches"
        assert result == expected

    def test_no_default_segments_returns_base(self, monkeypatch):
        monkeypatch.delenv("KAIZEN_TEST_DIR", raising=False)
        result = env_overridable_dir("KAIZEN_TEST_DIR")
        assert result == Path.home() / ".claude" / ".kaizen"

class TestBaseOverride:
    def test_base_overrides_default_root(self, monkeypatch):
        monkeypatch.delenv("KAIZEN_TEST_DIR", raising=False)
        custom = Path("/var/lib/kaizen")
        result = env_overridable_dir("KAIZEN_TEST_DIR", "sub",
                                       base=custom)
        assert result == custom / "sub"

class TestDeterministic:
    def test_same_inputs_same_output(self, monkeypatch):
        monkeypatch.delenv("KAIZEN_TEST_DIR", raising=False)
        a = env_overridable_dir("KAIZEN_TEST_DIR", "x")
        b = env_overridable_dir("KAIZEN_TEST_DIR", "x")
        assert a == b
