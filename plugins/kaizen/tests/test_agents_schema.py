#!/usr/bin/env python3
"""Schema validation for agents/ markdown files.

Run:
    python3 -m unittest tests.test_agents_schema -v
    OR
    python3 tests/test_agents_schema.py

Covers:
    - Each agent has the required frontmatter fields (name, description, tools)
    - tools field is a JSON-array literal Claude Code can parse
    - description is non-empty (it's the routing surface)
    - body is non-trivial (>30 lines — agents shouldn't be stubs)
    - All 3 v1.3.0 agents are present
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

REQUIRED_AGENTS = {
    "kaizen-reviewer",
    "kaizen-backlog-curator",
    "kaizen-debt-auditor",
}

REQUIRED_FRONTMATTER = {"name", "description"}
RECOMMENDED_FRONTMATTER = {"tools", "model"}


def parse_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def frontmatter_keys(fm: str) -> set[str]:
    """Top-level YAML keys (no nesting). Handles `key:` and `key: value`."""
    return {
        m.group(1)
        for line in fm.split("\n")
        if (m := re.match(r"^([a-z_]+):", line))
    }


def get_field(fm: str, key: str) -> str:
    """Return the value of a top-level scalar field, including '|' block scalars."""
    lines = fm.split("\n")
    for i, line in enumerate(lines):
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if not m:
            continue
        val = m.group(1).strip()
        if val == "|":
            # Block scalar — collect indented continuation lines
            body = []
            for j in range(i + 1, len(lines)):
                cont = lines[j]
                if cont and not cont.startswith(" "):
                    break
                body.append(cont.lstrip(" "))
            return "\n".join(body).strip()
        return val
    return ""


class TestAgentsExist(unittest.TestCase):
    def test_all_three_present(self):
        present = {f.stem for f in AGENTS_DIR.glob("*.md")}
        for required in REQUIRED_AGENTS:
            self.assertIn(required, present, f"missing agent: {required}")

    def test_no_unexpected_files(self):
        # Catch typos like .md.bak, READEM.md, etc.
        for f in AGENTS_DIR.glob("*"):
            self.assertTrue(
                f.suffix == ".md" or f.is_dir(),
                f"unexpected file in agents/: {f.name}",
            )


class TestAgentSchema(unittest.TestCase):
    def test_frontmatter_required_fields(self):
        for agent in REQUIRED_AGENTS:
            with self.subTest(agent=agent):
                path = AGENTS_DIR / f"{agent}.md"
                fm, _ = parse_frontmatter(path.read_text())
                self.assertNotEqual(fm, "", f"{agent}: missing frontmatter")
                keys = frontmatter_keys(fm)
                for req in REQUIRED_FRONTMATTER:
                    self.assertIn(req, keys, f"{agent}: missing required '{req}'")

    def test_name_matches_filename(self):
        for agent in REQUIRED_AGENTS:
            with self.subTest(agent=agent):
                path = AGENTS_DIR / f"{agent}.md"
                fm, _ = parse_frontmatter(path.read_text())
                name = get_field(fm, "name")
                self.assertEqual(name, agent, f"{agent}: name field != filename stem")

    def test_description_is_non_trivial(self):
        for agent in REQUIRED_AGENTS:
            with self.subTest(agent=agent):
                path = AGENTS_DIR / f"{agent}.md"
                fm, _ = parse_frontmatter(path.read_text())
                desc = get_field(fm, "description")
                self.assertGreaterEqual(
                    len(desc), 50,
                    f"{agent}: description too short ({len(desc)} chars)",
                )

    def test_tools_is_parseable_list(self):
        for agent in REQUIRED_AGENTS:
            with self.subTest(agent=agent):
                path = AGENTS_DIR / f"{agent}.md"
                fm, _ = parse_frontmatter(path.read_text())
                tools_raw = get_field(fm, "tools")
                self.assertTrue(
                    tools_raw.startswith("[") and tools_raw.endswith("]"),
                    f"{agent}: tools must be a JSON-style array, got: {tools_raw}",
                )
                # Should parse as JSON
                try:
                    tools = json.loads(tools_raw)
                except json.JSONDecodeError as e:
                    self.fail(f"{agent}: tools field is invalid JSON: {e}")
                self.assertIsInstance(tools, list)
                self.assertGreater(len(tools), 0, f"{agent}: empty tools list")

    def test_body_is_substantial(self):
        for agent in REQUIRED_AGENTS:
            with self.subTest(agent=agent):
                path = AGENTS_DIR / f"{agent}.md"
                _, body = parse_frontmatter(path.read_text())
                lines = [l for l in body.split("\n") if l.strip()]
                self.assertGreaterEqual(
                    len(lines), 30,
                    f"{agent}: body too thin ({len(lines)} non-empty lines)",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
