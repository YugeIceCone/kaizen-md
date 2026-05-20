"""TDD for mermaid_parse.py — flowchart/graph parser (stdlib-only).

Covers the common subset:
  - flowchart TD/LR/RL/BT/TB direction
  - node shapes: [], (), ((  )), [[  ]], [(  )], {}, {{  }}, [/  /], [\\  \\]
  - edge styles: -->, -.->, ==>, ---, -.->, -- text --, -->|label|, -. text .->
  - subgraph blocks with direction + name
  - classDef defining + ::: class assignment
  - %% comments
  - quoted node labels with special chars

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_mermaid_parse -v
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 — adds scripts/<cluster>/ to sys.path
import mermaid as mp


# ─── Direction ────────────────────────────────────────────────────────


class TestDirection(unittest.TestCase):
    def test_flowchart_td(self):
        r = mp.parse_flowchart("flowchart TD\n  A --> B")
        self.assertEqual(r["direction"], "TD")

    def test_flowchart_lr(self):
        r = mp.parse_flowchart("flowchart LR\n  A --> B")
        self.assertEqual(r["direction"], "LR")

    def test_graph_keyword_works_too(self):
        r = mp.parse_flowchart("graph BT\n  A --> B")
        self.assertEqual(r["direction"], "BT")

    def test_default_direction_when_omitted(self):
        r = mp.parse_flowchart("flowchart\n  A --> B")
        self.assertEqual(r["direction"], "TB")


# ─── Nodes ────────────────────────────────────────────────────────────


class TestNodes(unittest.TestCase):
    def test_bare_id_node(self):
        r = mp.parse_flowchart("flowchart TD\n  A --> B")
        ids = [n["id"] for n in r["nodes"]]
        self.assertIn("A", ids)
        self.assertIn("B", ids)

    def test_rect_label(self):
        r = mp.parse_flowchart("flowchart TD\n  A[hello world] --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["label"], "hello world")
        self.assertEqual(n["shape"], "rect")

    def test_round_shape(self):
        r = mp.parse_flowchart("flowchart TD\n  A(round node) --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "round")
        self.assertEqual(n["label"], "round node")

    def test_circle_shape(self):
        r = mp.parse_flowchart("flowchart TD\n  A((circle)) --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "circle")

    def test_decision_shape(self):
        r = mp.parse_flowchart("flowchart TD\n  A{maybe?} --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "diamond")
        self.assertEqual(n["label"], "maybe?")

    def test_storage_shape(self):
        r = mp.parse_flowchart("flowchart TD\n  A[(db)] --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "cylinder")

    def test_subroutine_shape(self):
        r = mp.parse_flowchart("flowchart TD\n  A[[sub]] --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "subroutine")

    def test_hex_shape(self):
        r = mp.parse_flowchart("flowchart TD\n  A{{hex}} --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "hexagon")

    def test_quoted_label_with_special_chars(self):
        r = mp.parse_flowchart('flowchart TD\n  A["Hello (world)!"] --> B')
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["label"], "Hello (world)!")

    def test_node_dedup_across_edges(self):
        r = mp.parse_flowchart("flowchart TD\n  A --> B\n  B --> A")
        ids = [n["id"] for n in r["nodes"]]
        self.assertEqual(sorted(ids), ["A", "B"])

    def test_node_label_persists_when_redefined_bare(self):
        # A[label] defined once + referenced bare later — keep the label
        r = mp.parse_flowchart("flowchart TD\n  A[first] --> B\n  A --> C")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["label"], "first")


# ─── Edges ────────────────────────────────────────────────────────────


class TestEdges(unittest.TestCase):
    def test_simple_arrow(self):
        r = mp.parse_flowchart("flowchart TD\n  A --> B")
        self.assertEqual(len(r["edges"]), 1)
        e = r["edges"][0]
        self.assertEqual(e["from"], "A")
        self.assertEqual(e["to"], "B")
        self.assertEqual(e["style"], "solid")

    def test_dotted_arrow(self):
        r = mp.parse_flowchart("flowchart TD\n  A -.-> B")
        e = r["edges"][0]
        self.assertEqual(e["style"], "dotted")

    def test_thick_arrow(self):
        r = mp.parse_flowchart("flowchart TD\n  A ==> B")
        e = r["edges"][0]
        self.assertEqual(e["style"], "thick")

    def test_link_no_arrow(self):
        r = mp.parse_flowchart("flowchart TD\n  A --- B")
        e = r["edges"][0]
        self.assertEqual(e["style"], "solid")
        self.assertFalse(e["arrow"])

    def test_label_with_pipe_syntax(self):
        r = mp.parse_flowchart('flowchart TD\n  A -->|hello| B')
        e = r["edges"][0]
        self.assertEqual(e["label"], "hello")

    def test_label_with_inline_text_syntax(self):
        r = mp.parse_flowchart("flowchart TD\n  A -- hello --> B")
        e = r["edges"][0]
        self.assertEqual(e["label"], "hello")

    def test_dotted_label_with_dotsyntax(self):
        r = mp.parse_flowchart("flowchart TD\n  A -. hello world .-> B")
        e = r["edges"][0]
        self.assertEqual(e["style"], "dotted")
        self.assertEqual(e["label"], "hello world")


# ─── Subgraphs ────────────────────────────────────────────────────────


class TestSubgraphs(unittest.TestCase):
    def test_subgraph_with_id_and_title(self):
        text = """\
flowchart TD
    subgraph G1 [Group One]
        A --> B
    end
"""
        r = mp.parse_flowchart(text)
        self.assertEqual(len(r["subgraphs"]), 1)
        sg = r["subgraphs"][0]
        self.assertEqual(sg["id"], "G1")
        self.assertEqual(sg["label"], "Group One")
        self.assertIn("A", sg["node_ids"])
        self.assertIn("B", sg["node_ids"])

    def test_subgraph_direction_directive(self):
        text = """\
flowchart TD
    subgraph G1 [Group]
        direction LR
        A --> B
    end
"""
        r = mp.parse_flowchart(text)
        sg = r["subgraphs"][0]
        self.assertEqual(sg["direction"], "LR")

    def test_subgraph_without_label(self):
        text = "flowchart TD\n    subgraph G\n        A --> B\n    end"
        r = mp.parse_flowchart(text)
        sg = r["subgraphs"][0]
        self.assertEqual(sg["id"], "G")


# ─── classDef + ::: assignment ────────────────────────────────────────


class TestClassDef(unittest.TestCase):
    def test_classdef_capture(self):
        text = "flowchart TD\n    classDef foo fill:#f00,stroke:#000\n    A --> B"
        r = mp.parse_flowchart(text)
        self.assertEqual(len(r["class_defs"]), 1)
        cd = r["class_defs"][0]
        self.assertEqual(cd["name"], "foo")
        self.assertEqual(cd["style"]["fill"], "#f00")
        self.assertEqual(cd["style"]["stroke"], "#000")

    def test_class_assignment_via_triple_colon(self):
        text = "flowchart TD\n    A[hi]:::foo --> B"
        r = mp.parse_flowchart(text)
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertIn("foo", n["classes"])

    def test_class_assignment_on_bare_node(self):
        text = "flowchart TD\n    A:::foo --> B"
        r = mp.parse_flowchart(text)
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertIn("foo", n["classes"])


# ─── Comments + blank lines ───────────────────────────────────────────


class TestComments(unittest.TestCase):
    def test_pct_comments_stripped(self):
        text = """\
flowchart TD
    %% this is a comment
    A --> B
    %% another
"""
        r = mp.parse_flowchart(text)
        self.assertEqual(len(r["edges"]), 1)

    def test_blank_lines_ok(self):
        r = mp.parse_flowchart("flowchart TD\n\n  A --> B\n\n")
        self.assertEqual(len(r["edges"]), 1)


# ─── CLI smoke ────────────────────────────────────────────────────────


class TestCLI(unittest.TestCase):
    def test_main_with_file_emits_json(self):
        import json
        import subprocess
        import tempfile

        script = (Path(__file__).resolve().parent.parent
                   / "scripts" / "util" / "mermaid.py")
        with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False) as f:
            f.write("flowchart TD\n  A[hi] --> B")
            tmp = f.name

        result = subprocess.run(
            [sys.executable, str(script), "parse", tmp],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["direction"], "TD")
        self.assertEqual(len(payload["edges"]), 1)


# ═══════════════════════════════════════════════════════════════════
# v2 — extended Mermaid surface (per references/mermaid-flowchart-api.md)
# ═══════════════════════════════════════════════════════════════════


# ─── v2: Extended arrow types ─────────────────────────────────────────


class TestArrowTypesV2(unittest.TestCase):
    def test_bidirectional(self):
        r = mp.parse_flowchart("flowchart TD\n  A <--> B")
        e = r["edges"][0]
        self.assertEqual(e["direction"], "both")
        self.assertEqual(e["head"], "arrow")

    def test_cross_right(self):
        r = mp.parse_flowchart("flowchart TD\n  A --x B")
        e = r["edges"][0]
        self.assertEqual(e["head"], "cross")
        self.assertEqual(e["direction"], "right")

    def test_cross_both(self):
        r = mp.parse_flowchart("flowchart TD\n  A x--x B")
        e = r["edges"][0]
        self.assertEqual(e["head"], "cross")
        self.assertEqual(e["direction"], "both")

    def test_circle_right(self):
        r = mp.parse_flowchart("flowchart TD\n  A --o B")
        e = r["edges"][0]
        self.assertEqual(e["head"], "circle")
        self.assertEqual(e["direction"], "right")

    def test_circle_both(self):
        r = mp.parse_flowchart("flowchart TD\n  A o--o B")
        e = r["edges"][0]
        self.assertEqual(e["head"], "circle")
        self.assertEqual(e["direction"], "both")

    def test_default_arrow_head(self):
        r = mp.parse_flowchart("flowchart TD\n  A --> B")
        e = r["edges"][0]
        self.assertEqual(e["head"], "arrow")
        self.assertEqual(e["direction"], "right")

    def test_length_extra_dashes(self):
        r = mp.parse_flowchart("flowchart TD\n  A ----> B")
        e = r["edges"][0]
        # 4 dashes = 2 extra over baseline 2 → length 2
        self.assertEqual(e["length"], 2)


# ─── v2: Extra shape forms ────────────────────────────────────────────


class TestExtraShapesV2(unittest.TestCase):
    def test_triple_paren_double_circle(self):
        r = mp.parse_flowchart("flowchart TD\n  A(((dbl))) --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "double-circle")

    def test_stadium_pill(self):
        r = mp.parse_flowchart("flowchart TD\n  A([pill]) --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "stadium")

    def test_asymmetric_flag(self):
        r = mp.parse_flowchart("flowchart TD\n  A>flag] --> B")
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "asymmetric")


# ─── v2: New @{ shape: ..., label: ... } syntax ──────────────────────


class TestNewShapeSyntaxV2(unittest.TestCase):
    def test_at_brace_shape(self):
        r = mp.parse_flowchart('flowchart LR\n  A1@{ shape: cloud, label: hi }')
        n = next(n for n in r["nodes"] if n["id"] == "A1")
        self.assertEqual(n["shape"], "cloud")
        self.assertEqual(n["label"], "hi")

    def test_at_brace_with_quoted_label(self):
        r = mp.parse_flowchart('flowchart LR\n  A@{ shape: tag-rect, label: "Hello (world)" }')
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["shape"], "tag-rect")
        self.assertEqual(n["label"], "Hello (world)")


# ─── v2: Multi-node ampersand sugar ───────────────────────────────────


class TestAmpersandV2(unittest.TestCase):
    def test_lhs_ampersand_fans_out(self):
        r = mp.parse_flowchart("flowchart TD\n  A & B --> C")
        froms = sorted(e["from"] for e in r["edges"])
        self.assertEqual(froms, ["A", "B"])
        self.assertTrue(all(e["to"] == "C" for e in r["edges"]))

    def test_rhs_ampersand_fans_out(self):
        r = mp.parse_flowchart("flowchart TD\n  A --> B & C")
        tos = sorted(e["to"] for e in r["edges"])
        self.assertEqual(tos, ["B", "C"])

    def test_both_sides_cartesian(self):
        r = mp.parse_flowchart("flowchart TD\n  A & B --> C & D")
        self.assertEqual(len(r["edges"]), 4)


# ─── v2: Class assignment via `class A,B name` ────────────────────────


class TestClassStatementV2(unittest.TestCase):
    def test_multi_node_class_assignment(self):
        text = """\
flowchart TD
    A --> B
    A --> C
    class A,B,C marked
"""
        r = mp.parse_flowchart(text)
        for nid in ("A", "B", "C"):
            n = next(n for n in r["nodes"] if n["id"] == nid)
            self.assertIn("marked", n["classes"])


# ─── v2: Per-node style + per-edge linkStyle ──────────────────────────


class TestStyleStatementsV2(unittest.TestCase):
    def test_style_per_node(self):
        text = "flowchart TD\n  A --> B\n  style A fill:#f00,stroke:#000"
        r = mp.parse_flowchart(text)
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["style"]["fill"], "#f00")
        self.assertEqual(n["style"]["stroke"], "#000")

    def test_linkstyle_by_index(self):
        text = "flowchart TD\n  A --> B\n  linkStyle 0 stroke:#f00"
        r = mp.parse_flowchart(text)
        self.assertEqual(len(r["link_styles"]), 1)
        ls = r["link_styles"][0]
        self.assertEqual(ls["target"], 0)
        self.assertEqual(ls["style"]["stroke"], "#f00")

    def test_linkstyle_default(self):
        text = "flowchart TD\n  A --> B\n  linkStyle default stroke:#0f0"
        r = mp.parse_flowchart(text)
        ls = r["link_styles"][0]
        self.assertEqual(ls["target"], "default")


# ─── v2: click handlers ───────────────────────────────────────────────


class TestClickV2(unittest.TestCase):
    def test_click_url(self):
        text = 'flowchart TD\n  A --> B\n  click A "https://example.com"'
        r = mp.parse_flowchart(text)
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["click"]["target"], "https://example.com")

    def test_click_with_tooltip(self):
        text = 'flowchart TD\n  A --> B\n  click A "https://x" "tooltip"'
        r = mp.parse_flowchart(text)
        n = next(n for n in r["nodes"] if n["id"] == "A")
        self.assertEqual(n["click"]["tooltip"], "tooltip")


# ─── v2: %%{init: ...}%% directive (skipped, not crashed) ────────────


class TestInitDirectiveV2(unittest.TestCase):
    def test_init_directive_ignored(self):
        text = "%%{init: {'theme':'dark'}}%%\nflowchart TD\n  A --> B"
        r = mp.parse_flowchart(text)
        self.assertEqual(r["direction"], "TD")
        self.assertEqual(len(r["edges"]), 1)


if __name__ == "__main__":
    unittest.main()
