"""Tests for the audit MCP server.

Verifies the markdown-report parser against the canonical kaizen-audit
format, plus delegation through the MCP tool wrappers. The shell `audit_run`
tool isn't exercised live (it runs the full repo audit) — only the parse +
read/list/findings paths, which is where the bulk of the MCP value sits.

Run:
    python3 -m unittest tests.test_audit_mcp -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "mcp"))

SAMPLE_REPORT = """# kaizen audit — 2026-05-12T18:56:59Z

**Scope:** (whole repo)
**Total findings:** 7

Per [synavos.com/code-review-vs-code-audit](https://example.com):
audit is comprehensive + periodic + severity-classified.

## HIGH — 2

- architecture | onion violation: 1 file(s) in crates/core/ import outer-ring crate 'tokio'
- coverage | test-file ratio 0% (0 tests / 769 src) — below recommended 10%

## MEDIUM — 2

- security | unsafe { ... } in 11 non-ffi file(s) — audit each block for soundness
- compliance | no LICENSE file — adopting an open-source license clarifies use

## LOW — 1

- architecture | module declarations (pub mod) density is high — consider dead-code audit

## INFO — 2

- tech-debt | 3 TODO/FIXME/XXX/HACK markers
- dependencies | run `cargo tree --depth 1` for direct-dep audit

---
"""

SAMPLE_NO_FINDINGS = """# kaizen audit — 2026-05-14T01:00:00Z

**Scope:** (whole repo)
**Total findings:** 0

All clear!

---
"""

def _import_mcp():
    if "audit_mcp" in sys.modules:
        del sys.modules["audit_mcp"]
    import audit_mcp
    return audit_mcp

# ─── parse_report ─────────────────────────────────────────────────────

class TestParseReport(unittest.TestCase):
    def test_extracts_scope(self):
        m = _import_mcp()
        p = m.parse_report(SAMPLE_REPORT)
        self.assertEqual(p["scope"], "(whole repo)")

    def test_extracts_total(self):
        m = _import_mcp()
        p = m.parse_report(SAMPLE_REPORT)
        self.assertEqual(p["total"], 7)

    def test_extracts_findings_per_severity(self):
        m = _import_mcp()
        p = m.parse_report(SAMPLE_REPORT)
        by_sev = {}
        for f in p["findings"]:
            by_sev.setdefault(f["severity"], []).append(f["text"])
        self.assertEqual(len(by_sev.get("HIGH", [])), 2)
        self.assertEqual(len(by_sev.get("MEDIUM", [])), 2)
        self.assertEqual(len(by_sev.get("LOW", [])), 1)
        self.assertEqual(len(by_sev.get("INFO", [])), 2)

    def test_preserves_finding_text(self):
        m = _import_mcp()
        p = m.parse_report(SAMPLE_REPORT)
        high = [f for f in p["findings"] if f["severity"] == "HIGH"]
        self.assertTrue(any("onion violation" in f["text"] for f in high))
        self.assertTrue(any("test-file ratio" in f["text"] for f in high))

    def test_zero_findings(self):
        m = _import_mcp()
        p = m.parse_report(SAMPLE_NO_FINDINGS)
        self.assertEqual(p["total"], 0)
        self.assertEqual(p["findings"], [])

    def test_handles_missing_header_fields(self):
        m = _import_mcp()
        p = m.parse_report("# audit\n\nbody\n")
        self.assertEqual(p["scope"], "")
        self.assertEqual(p["total"], 0)
        self.assertEqual(p["findings"], [])

# ─── MCP tools (read paths) ───────────────────────────────────────────

class _AuditsTmp:
    """Sandboxed audits dir for tests."""

    def __enter__(self):
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        self.audits = self.tmp / ".kaizen" / "workflow" / "audits"
        self.audits.mkdir(parents=True)
        self._saved = os.environ.get("KAIZEN_AUDITS_DIR")
        os.environ["KAIZEN_AUDITS_DIR"] = str(self.audits)
        return self

    def write(self, name: str, body: str) -> Path:
        p = self.audits / name
        p.write_text(body)
        return p

    def __exit__(self, *_):
        if self._saved is None:
            os.environ.pop("KAIZEN_AUDITS_DIR", None)
        else:
            os.environ["KAIZEN_AUDITS_DIR"] = self._saved
        self._tmpcm.cleanup()

class TestAuditList(unittest.TestCase):
    def test_returns_empty_when_no_audits(self):
        with _AuditsTmp():
            m = _import_mcp()
            self.assertEqual(asyncio.run(m.audit_list()), [])

    def test_lists_newest_first(self):
        with _AuditsTmp() as t:
            t.write("2026-05-10T00-00-00Z-repo.md", SAMPLE_REPORT)
            t.write("2026-05-14T00-00-00Z-repo.md", SAMPLE_REPORT)
            t.write("2026-05-12T00-00-00Z-repo.md", SAMPLE_REPORT)
            m = _import_mcp()
            out = asyncio.run(m.audit_list())
            names = [r["name"] for r in out]
            self.assertEqual(names[0], "2026-05-14T00-00-00Z-repo.md")
            self.assertEqual(names[-1], "2026-05-10T00-00-00Z-repo.md")

class TestAuditLatest(unittest.TestCase):
    def test_returns_present_false_when_no_audits(self):
        with _AuditsTmp():
            m = _import_mcp()
            out = asyncio.run(m.audit_latest())
            self.assertFalse(out["present"])

    def test_returns_summary_of_newest(self):
        with _AuditsTmp() as t:
            t.write("2026-05-10T00-00-00Z-repo.md", SAMPLE_NO_FINDINGS)
            t.write("2026-05-14T00-00-00Z-repo.md", SAMPLE_REPORT)
            m = _import_mcp()
            out = asyncio.run(m.audit_latest())
            self.assertTrue(out["present"])
            self.assertEqual(out["name"], "2026-05-14T00-00-00Z-repo.md")
            self.assertEqual(out["total"], 7)
            self.assertEqual(out["by_severity"]["HIGH"], 2)

class TestAuditRead(unittest.TestCase):
    def test_returns_full_body(self):
        with _AuditsTmp() as t:
            t.write("rpt.md", SAMPLE_REPORT)
            m = _import_mcp()
            out = asyncio.run(m.audit_read("rpt.md"))
            self.assertIn("body", out)
            self.assertIn("onion violation", out["body"])
            self.assertEqual(len(out["findings"]), 7)

    def test_missing_file_returns_error(self):
        with _AuditsTmp():
            m = _import_mcp()
            out = asyncio.run(m.audit_read("nonexistent.md"))
            self.assertIn("error", out)

class TestAuditFindings(unittest.TestCase):
    def test_returns_all_when_no_filter(self):
        with _AuditsTmp() as t:
            t.write("rpt.md", SAMPLE_REPORT)
            m = _import_mcp()
            out = asyncio.run(m.audit_findings())
            self.assertEqual(len(out), 7)

    def test_filters_by_severity(self):
        with _AuditsTmp() as t:
            t.write("rpt.md", SAMPLE_REPORT)
            m = _import_mcp()
            out = asyncio.run(m.audit_findings(severity="HIGH"))
            self.assertEqual(len(out), 2)
            self.assertTrue(all(f["severity"] == "HIGH" for f in out))

    def test_filters_by_scope_substring(self):
        with _AuditsTmp() as t:
            t.write("rpt.md", SAMPLE_REPORT)
            m = _import_mcp()
            out = asyncio.run(m.audit_findings(scope="architecture"))
            self.assertEqual(len(out), 2)
            self.assertTrue(all("architecture" in f["text"].lower() for f in out))

    def test_returns_empty_when_no_reports(self):
        with _AuditsTmp():
            m = _import_mcp()
            out = asyncio.run(m.audit_findings())
            self.assertEqual(out, [])

    def test_severity_case_insensitive(self):
        with _AuditsTmp() as t:
            t.write("rpt.md", SAMPLE_REPORT)
            m = _import_mcp()
            out_lower = asyncio.run(m.audit_findings(severity="high"))
            out_upper = asyncio.run(m.audit_findings(severity="HIGH"))
            self.assertEqual(len(out_lower), len(out_upper))

class TestRegistration(unittest.TestCase):
    def test_mcp_json_lists_audit_server(self):
        data = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
        # All domain servers are composed through the kaizen gateway
        self.assertIn("kaizen", data["mcpServers"])
        joined = " ".join(data["mcpServers"]["kaizen"]["args"])
        self.assertIn("gateway.py", joined)
        import gateway
        module_names = [m for _, m in gateway.SUBSERVERS]
        self.assertIn("audit_mcp", module_names)

if __name__ == "__main__":
    unittest.main()
