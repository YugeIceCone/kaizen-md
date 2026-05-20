"""Regression test for flow.py::WriteReport — CrateProfile dataclass access.

Locks in the fix for a bug surfaced during Tier-2 commit C smoke-test:
WriteReport.exec_async previously treated `doc_records` as list-of-dicts
(r["loc"]["total"]) but docs_gen.analyze_package returns CrateProfile
dataclass instances. Subscripting a dataclass raises TypeError, so the
demo failed on any non-empty workspace.

Empty workspace masked the bug because the buggy expression was inside
a `sum(...)` over an empty list, which never evaluates the predicate.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

class TestWriteReportConsumesDataclasses(unittest.TestCase):
    """WriteReport.exec_async must use attribute access on CrateProfile."""

    def test_exec_async_aggregates_dataclass_records(self):
        import flow
        import docs_gen

        records = [
            docs_gen.CrateProfile(
                name="alpha",
                relative_path="alpha",
                package_name="alpha",
                language="rust",
                files=[
                    docs_gen.FileProfile(
                        path="src/lib.rs",
                        loc=120,
                        blank_lines=5,
                        comment_lines=10,
                        module_doc=None,
                    ),
                    docs_gen.FileProfile(
                        path="src/main.rs",
                        loc=30,
                        blank_lines=2,
                        comment_lines=1,
                        module_doc=None,
                    ),
                ],
                total_loc=150,
            ),
            docs_gen.CrateProfile(
                name="beta",
                relative_path="beta",
                package_name="beta",
                language="python",
                files=[
                    docs_gen.FileProfile(
                        path="beta.py",
                        loc=80,
                        blank_lines=4,
                        comment_lines=6,
                        module_doc=None,
                    ),
                ],
                total_loc=80,
            ),
        ]

        node = flow.WriteReport()
        data = {
            "doc_records": records,
            "workspace_root": "/tmp/anywhere",
            "backlog_size": 0,
            "package_count": 2,
            "timing": {},
        }

        summary = asyncio.run(node.exec_async(data))

        self.assertEqual(summary["packages_scanned"], 2)
        self.assertEqual(summary["total_loc"], 230)  # 150 + 80
        self.assertEqual(summary["total_files"], 3)  # 2 + 1
        self.assertEqual(summary["by_language"], {"rust": 1, "python": 1})
        self.assertEqual(summary["top_5_by_loc"][0]["name"], "alpha")
        self.assertEqual(summary["top_5_by_loc"][0]["loc"], 150)
        self.assertEqual(summary["top_5_by_loc"][1]["name"], "beta")

    def test_exec_async_handles_empty_records(self):
        """Pre-fix this worked accidentally (sum over empty)."""
        import flow
        node = flow.WriteReport()
        data = {
            "doc_records": [],
            "workspace_root": "/tmp/empty",
            "backlog_size": 0,
            "package_count": 0,
            "timing": {},
        }
        summary = asyncio.run(node.exec_async(data))
        self.assertEqual(summary["packages_scanned"], 0)
        self.assertEqual(summary["total_loc"], 0)
        self.assertEqual(summary["total_files"], 0)
        self.assertEqual(summary["by_language"], {})
        self.assertEqual(summary["top_5_by_loc"], [])

if __name__ == "__main__":
    unittest.main()
