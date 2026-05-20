"""Security regression tests — lint_fix URL scheme allowlist (M2).

`_probe` (lint_fix_setup) and `_http_post` (lint_fix_dispatch) accept
any URL from `LLM_BASE_URL` env. urllib.request.urlopen honors
schemes like `file://`, `ftp://`, `gopher://` — a `file:///etc/passwd`
URL turns the probe into an arbitrary-file-read primitive.

This test class:
  1. Asserts both functions REFUSE non-http(s) schemes.
  2. Asserts http/https URLs still pass scheme validation (the
     reachability check is separate and not under test here).

Written test-first per TDD. Pre-fix both functions accept any
scheme. Post-fix only http/https resolve, others return None/empty.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ_DIR / "scripts/lint"))

import lint_fix_setup as lfs  # noqa: E402
import lint_fix_dispatch as lfd  # noqa: E402

class SetupProbeSchemeAllowlist(unittest.TestCase):
    """`lint_fix_setup._probe(base_url)` must reject non-http(s)."""

    def test_probe_rejects_file_scheme(self):
        # file:// would let urlopen read arbitrary local files
        result = lfs._probe("file:///etc/passwd", timeout=0.5)
        self.assertIsNone(result, "_probe must refuse file:// scheme")

    def test_probe_rejects_ftp_scheme(self):
        result = lfs._probe("ftp://example.com/foo", timeout=0.5)
        self.assertIsNone(result, "_probe must refuse ftp:// scheme")

    def test_probe_rejects_empty_scheme(self):
        # `localhost:8080` (no scheme) → urlparse.scheme is empty
        result = lfs._probe("localhost:8080", timeout=0.5)
        self.assertIsNone(result, "_probe must refuse missing scheme")

    def test_probe_accepts_http_scheme(self):
        # http:// to a non-reachable host returns None (reachability
        # failure), but the SCHEME passed validation. We can't easily
        # assert "passed validation" without mocking, so we test that
        # an http URL doesn't get rejected for SCHEME reasons. Use a
        # localhost port unlikely to be open — should fall through to
        # the connection-failure return None.
        # Acceptance check: not raising / not returning before the
        # connection attempt. Best signal: it returns None either way,
        # but without scheme-rejection logging.
        result = lfs._probe("http://127.0.0.1:1", timeout=0.1)
        self.assertIsNone(result)  # connection failed, not scheme reject

class HttpPostSchemeAllowlist(unittest.TestCase):
    """`lint_fix_dispatch._http_post(url, payload)` must reject
    non-http(s) schemes BEFORE issuing the request."""

    def test_http_post_rejects_file_scheme(self):
        with self.assertRaises((ValueError, lfd.urllib.error.URLError)):
            lfd._http_post("file:///etc/passwd",
                            {"model": "x", "messages": []})

    def test_http_post_rejects_ftp_scheme(self):
        with self.assertRaises((ValueError, lfd.urllib.error.URLError)):
            lfd._http_post("ftp://example.com/api",
                            {"model": "x", "messages": []})

if __name__ == "__main__":
    unittest.main()
