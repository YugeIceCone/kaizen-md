#!/usr/bin/env python3
"""Unit tests for cache.py — pure-Python, no subprocess.

Run:
    python3 -m unittest tests.test_cache -v
    OR
    python3 tests/test_cache.py

Covers:
    - key_of: determinism, separator safety, length
    - put / get round-trip
    - get miss returns None
    - delete + miss-after-delete
    - clear removes all entries
    - stats reports count + bytes accurately
    - cache_dir() respects KAIZEN_CACHE_DIR override
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

def _fresh_cache(tmp: Path) -> ModuleType:
    """Import cache.py with KAIZEN_CACHE_DIR pointing at a fresh tmp dir."""
    os.environ["KAIZEN_CACHE_DIR"] = str(tmp)
    if "cache" in sys.modules:
        del sys.modules["cache"]
    import cache  # noqa: E402
    return cache

class TestKey(unittest.TestCase):
    def test_determinism(self):
        tmp = Path(tempfile.mkdtemp())
        c = _fresh_cache(tmp)
        k1 = c.key_of("a", "b", "c")
        k2 = c.key_of("a", "b", "c")
        self.assertEqual(k1, k2)

    def test_separator_safety(self):
        tmp = Path(tempfile.mkdtemp())
        c = _fresh_cache(tmp)
        # Without separator, ['ab', 'c'] and ['a', 'bc'] would collide.
        self.assertNotEqual(c.key_of("ab", "c"), c.key_of("a", "bc"))

    def test_length(self):
        tmp = Path(tempfile.mkdtemp())
        c = _fresh_cache(tmp)
        k = c.key_of("input")
        self.assertEqual(len(k), 16)
        # Hex only
        self.assertTrue(all(ch in "0123456789abcdef" for ch in k))

class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.c = _fresh_cache(self.tmp)

    def test_put_get(self):
        k = self.c.key_of("test")
        self.c.put(k, {"status": "pass", "n": 42})
        result = self.c.get(k)
        self.assertEqual(result, {"status": "pass", "n": 42})

    def test_get_miss(self):
        self.assertIsNone(self.c.get("no-such-key"))

    def test_delete(self):
        k = self.c.key_of("doomed")
        self.c.put(k, {"v": 1})
        self.assertTrue(self.c.delete(k))
        self.assertIsNone(self.c.get(k))

    def test_delete_miss(self):
        self.assertFalse(self.c.delete("ghost"))

class TestClear(unittest.TestCase):
    def test_clear_removes_all(self):
        tmp = Path(tempfile.mkdtemp())
        c = _fresh_cache(tmp)
        for i in range(5):
            c.put(c.key_of(f"k{i}"), {"i": i})
        n = c.clear()
        self.assertEqual(n, 5)
        self.assertEqual(c.stats()["count"], 0)

class TestStats(unittest.TestCase):
    def test_stats_count(self):
        tmp = Path(tempfile.mkdtemp())
        c = _fresh_cache(tmp)
        c.put(c.key_of("a"), {"v": 1})
        c.put(c.key_of("b"), {"v": 2})
        self.assertEqual(c.stats()["count"], 2)

    def test_stats_empty_dir(self):
        tmp = Path(tempfile.mkdtemp())
        c = _fresh_cache(tmp)
        # cache_dir doesn't exist until first write
        s = c.stats()
        self.assertEqual(s["count"], 0)
        self.assertEqual(s["bytes"], 0)

class TestEnvOverride(unittest.TestCase):
    def test_kaizen_cache_dir_env(self):
        tmp = Path(tempfile.mkdtemp()) / "alt-cache"
        c = _fresh_cache(tmp)
        self.assertEqual(c.cache_dir(), tmp)
        c.put(c.key_of("x"), {"v": 1})
        self.assertTrue((tmp / f"{c.key_of('x')}.json").exists())

class TestCorruption(unittest.TestCase):
    def test_corrupt_json_returns_none(self):
        tmp = Path(tempfile.mkdtemp())
        c = _fresh_cache(tmp)
        k = c.key_of("corrupt")
        # Write garbage to the cache file
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / f"{k}.json").write_text("not valid json {{{")
        # get should swallow the error and return None
        self.assertIsNone(c.get(k))

if __name__ == "__main__":
    unittest.main(verbosity=2)
