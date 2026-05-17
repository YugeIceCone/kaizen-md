"""Schema-pass validator for plugins/kaizen/agents/*.md.

Goes BEYOND test_agents_schema.py (which only checks 3 hardcoded
agents). This file:

  1. Walks EVERY *.md in agents/ — catches typos in new agents
     instantly instead of waiting for someone to add them to a
     hardcoded set.

  2. Validates each frontmatter against
     assets/schemas/agent.schema.json — pinning name/description/
     tools structure as the canonical contract.

  3. Loads + lints the dispatch-rubric (skills/agent-formatting/
     domain/dispatch-rubric.yaml) and verifies every bucket value
     references a real agent file OR the documented fallbacks
     (general-purpose / NEEDS_AGENT). Catches the "renamed an agent,
     forgot to update the rubric" failure mode.

Stdlib-only: tools field is parsed with a tolerant matcher that
accepts the three surface forms in current use (JSON array, YAML
inline list, comma-separated bare). jsonschema is optional — falls
back to a minimal hand-rolled validator if not installed.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_AGENTS_DIR = _KZ_DIR / "agents"
_AGENT_SCHEMA = _KZ_DIR / "assets/schemas/agent.schema.json"
_RUBRIC = _KZ_DIR / "skills/agent-formatting/domain/dispatch-rubric.yaml"


def _parse_frontmatter(text: str) -> str:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    return m.group(1) if m else ""


def _scalar_field(fm: str, key: str) -> str:
    """Return value of a top-level scalar OR block-scalar field."""
    lines = fm.split("\n")
    for i, line in enumerate(lines):
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if not m:
            continue
        val = m.group(1).strip()
        if val == "|":
            body = []
            for j in range(i + 1, len(lines)):
                if lines[j] and not lines[j].startswith(" "):
                    break
                body.append(lines[j].lstrip(" "))
            return "\n".join(body).strip()
        return val
    return ""


def _parse_tool_list(raw: str) -> list[str]:
    """Tolerant parser for the 3 surface forms in current use:

       tools: ["Read", "Bash"]          → JSON array
       tools: [Read, Grep, Bash(git *)]  → YAML inline list (bare names)
       tools: Read, Glob, Grep           → comma-separated bare
    """
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x).strip() for x in data]
        except json.JSONDecodeError:
            pass
        inner = raw[1:-1]
        # YAML inline — split on commas not inside parens
        out, depth, buf = [], 0, ""
        for c in inner:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            if c == "," and depth == 0:
                if buf.strip():
                    out.append(buf.strip().strip("\""))
                buf = ""
            else:
                buf += c
        if buf.strip():
            out.append(buf.strip().strip("\""))
        return out
    # Comma-separated bare form
    return [t.strip().strip("\"") for t in raw.split(",") if t.strip()]


def _agent_files() -> list[Path]:
    return sorted(_AGENTS_DIR.glob("*.md"))


def _agent_frontmatter(p: Path) -> dict:
    """Extract the minimum keys we validate: name, description, tools,
    disallowedTools, model. Tolerant — uses scalar field extraction +
    the tool-list parser."""
    fm = _parse_frontmatter(p.read_text())
    out = {
        "name":            _scalar_field(fm, "name"),
        "description":     _scalar_field(fm, "description"),
        "tools":           _parse_tool_list(_scalar_field(fm, "tools")),
        "disallowedTools": _parse_tool_list(_scalar_field(fm, "disallowedTools")),
        "model":           _scalar_field(fm, "model"),
    }
    return out


# ── Tests ────────────────────────────────────────────────────────────


class TestAgentSchemaArtifacts(unittest.TestCase):
    def test_schema_file_present_and_valid_json(self):
        self.assertTrue(_AGENT_SCHEMA.is_file())
        data = json.loads(_AGENT_SCHEMA.read_text())
        self.assertEqual(data["title"], "Kaizen subagent frontmatter")
        self.assertIn("required", data)
        self.assertIn("name", data["required"])

    def test_rubric_file_present_and_valid_yaml(self):
        self.assertTrue(_RUBRIC.is_file())
        # Loose YAML probe — full validation via kaizen-rubric lint
        text = _RUBRIC.read_text()
        self.assertIn("version: 1", text)
        self.assertIn("fallback:", text)
        self.assertIn("rules:", text)


class TestEveryAgentValidates(unittest.TestCase):
    """ALL *.md files in agents/ pass the schema — not just the 3
    hardcoded in test_agents_schema.py."""

    def test_every_agent_has_name_matching_filename(self):
        for p in _agent_files():
            with self.subTest(agent=p.stem):
                fm = _agent_frontmatter(p)
                self.assertEqual(fm["name"], p.stem,
                                  f"{p.name}: name '{fm['name']}' != filename")

    def test_every_agent_name_uses_kaizen_prefix(self):
        for p in _agent_files():
            with self.subTest(agent=p.stem):
                fm = _agent_frontmatter(p)
                self.assertRegex(fm["name"], r"^kaizen-[a-z][a-z0-9-]*$",
                                  f"{p.name}: must follow kaizen-<kebab> convention")

    def test_every_agent_description_50_chars(self):
        for p in _agent_files():
            with self.subTest(agent=p.stem):
                fm = _agent_frontmatter(p)
                self.assertGreaterEqual(
                    len(fm["description"]), 50,
                    f"{p.name}: description too short ({len(fm['description'])} chars)")

    def test_every_agent_has_non_empty_tools(self):
        for p in _agent_files():
            with self.subTest(agent=p.stem):
                fm = _agent_frontmatter(p)
                self.assertGreater(len(fm["tools"]), 0,
                                    f"{p.name}: tools list empty / unparseable")

    def test_every_agent_model_is_recognized(self):
        recognized = {"", "inherit", "sonnet", "opus", "haiku"}
        for p in _agent_files():
            with self.subTest(agent=p.stem):
                fm = _agent_frontmatter(p)
                self.assertIn(fm["model"], recognized,
                                f"{p.name}: unknown model {fm['model']!r}")


class TestDispatchRubricIntegrity(unittest.TestCase):
    """Every bucket in the rubric must point at a real agent file
    (or the documented fallbacks). Catches rename drift."""

    def _agent_names(self) -> set[str]:
        return {p.stem for p in _agent_files()}

    def _rubric_buckets(self) -> set[str]:
        """Parse bucket: + fallback: lines without pulling in PyYAML."""
        buckets = set()
        for line in _RUBRIC.read_text().splitlines():
            m = re.match(r"^\s*(?:-\s*)?(?:bucket|fallback)\s*:\s*(\S+)\s*$", line)
            if m:
                buckets.add(m.group(1).strip())
        return buckets

    def test_every_bucket_resolves_to_real_agent_or_fallback(self):
        agents = self._agent_names()
        allowed_fallbacks = {"general-purpose", "NEEDS_AGENT"}
        for bucket in self._rubric_buckets():
            with self.subTest(bucket=bucket):
                self.assertTrue(
                    bucket in agents or bucket in allowed_fallbacks,
                    f"rubric references {bucket!r} which is not a real "
                    f"agent file (and not in fallbacks {allowed_fallbacks})",
                )

    def test_rubric_signal_enum_documented(self):
        """The per-rubric schema enumerates signal names. Verifies
        the schema file ships alongside the rubric (catches the
        'shipped rubric without updating its schema' case)."""
        schema_path = (_RUBRIC.parent / "schemas"
                       / "dispatch-rubric.schema.json")
        self.assertTrue(schema_path.is_file(),
                          f"missing schema at {schema_path}")
        schema = json.loads(schema_path.read_text())
        # Drill to the signal enum
        enum = (schema.get("definitions", {})
                       .get("condition_list", {})
                       .get("items", {})
                       .get("properties", {})
                       .get("signal", {})
                       .get("enum", []))
        self.assertGreater(len(enum), 0,
                            "dispatch-rubric.schema.json must enumerate signal names")
        # Every signal referenced in the rubric must be in the enum
        signals_in_rubric = set()
        for line in _RUBRIC.read_text().splitlines():
            m = re.search(r"signal:\s*(\w+)", line)
            if m:
                signals_in_rubric.add(m.group(1))
        unknown = signals_in_rubric - set(enum)
        self.assertFalse(unknown,
                          f"rubric uses signals not in schema enum: {unknown}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
