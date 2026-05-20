# consolidated-cli-parent: mermaid
"""kaizen mermaid_parse — stdlib-only Mermaid flowchart/graph parser (v2).

Parses the common subset of Mermaid flowchart syntax into a structured
dict suitable for programmatic consumption.

For the COMPLETE surface inventory (what's parsed vs not), see:
  skills/workflow/references/mermaid-flowchart-api.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ─── Classic ASCII shape openers/closers ──────────────────────────────

_SHAPE_MAP: dict[tuple[str, str], str] = {
    ("(((", ")))"): "double-circle",
    ("([",  "])"):  "stadium",
    ("[(",  ")]"):  "cylinder",
    ("[[",  "]]"):  "subroutine",
    ("((",  "))"):  "circle",
    ("{{",  "}}"):  "hexagon",
    ("[/",  "/]"):  "parallelogram",
    ("[\\", "\\]"): "parallelogram-alt",
    ("[/",  "\\]"): "trapezoid",
    ("[\\", "/]"):  "trapezoid-alt",
    ("[",   "]"):   "rect",
    ("(",   ")"):   "round",
    ("{",   "}"):   "diamond",
}

# Order matters in regex alternation — longest tokens first.
_OPEN_ALT = r"\(\(\(|\(\[|\[\(|\[\[|\(\(|\{\{|\[/|\[\\|\[|\(|\{"
_CLOSE_ALT = r"\)\)\)|\]\)|\)\]|\]\]|\)\)|\}\}|/\]|\\\]|\]|\)|\}"

_NODE_QUOTED_RE = re.compile(
    r'^([A-Za-z0-9_-]+)'
    rf'({_OPEN_ALT})'
    r'"(.*?)"'
    rf'({_CLOSE_ALT})'
    r'(?::::([A-Za-z0-9_,]+))?'
)
_NODE_RE = re.compile(
    r'^([A-Za-z0-9_-]+)'
    rf'({_OPEN_ALT})'
    r'(.*?)'
    rf'({_CLOSE_ALT})'
    r'(?::::([A-Za-z0-9_,]+))?'
)
# Asymmetric / flag:  A>label]
_NODE_FLAG_RE = re.compile(
    r'^([A-Za-z0-9_-]+)>(.*?)\](?::::([A-Za-z0-9_,]+))?'
)
# Bare id maybe with :::classes
_BARE_RE = re.compile(r"^([A-Za-z0-9_-]+)(?::::([A-Za-z0-9_,]+))?$")

# New shape syntax (v11+): A@{ shape: name, label: text }
_AT_BRACE_RE = re.compile(r'^([A-Za-z0-9_-]+)@\{\s*(.*?)\s*\}$')

# ─── Statement regexes ───────────────────────────────────────────────

_RE_FLOWCHART = re.compile(r"^(?:flowchart|graph)(?:\s+([A-Z]{2}))?$")
_RE_CLASSDEF = re.compile(r"^classDef\s+([A-Za-z0-9_]+)\s+(.*)$")
_RE_CLASS_STMT = re.compile(r"^class\s+([A-Za-z0-9_,\s]+?)\s+([A-Za-z0-9_]+)$")
_RE_SUBGRAPH = re.compile(r'^subgraph\s+([A-Za-z0-9_-]+)(?:\s+\[([^\]]+)\])?$')
_RE_SUBGRAPH_QUOTED = re.compile(r'^subgraph\s+"([^"]+)"$')
_RE_END = re.compile(r"^end$")
_RE_DIRECTION = re.compile(r"^direction\s+([A-Z]{2})$")
_RE_STYLE = re.compile(r"^style\s+([A-Za-z0-9_-]+)\s+(.*)$")
_RE_LINKSTYLE = re.compile(r"^linkStyle\s+(default|\d+(?:,\d+)*)\s+(.*)$")
_RE_CLICK = re.compile(
    r'^click\s+([A-Za-z0-9_-]+)\s+(?:"([^"]*)"|(\S+))(?:\s+"([^"]*)")?$'
)
_RE_INIT = re.compile(r"^%%\{.*\}%%$")  # %%{init: ...}%%

# ─── Edge detection (v2 — heads + length + bidirectional) ────────────

_RE_DOTTED_LABEL_ARROW = re.compile(r'(<)?-\.\s+(.+?)\s+\.-(>|x|o)?')
_RE_SOLID_LABEL_ARROW = re.compile(r'(<|x|o)?(-{2,})\s+(.+?)\s+(-{2,})(>|x|o)?')
_RE_THICK_LABEL_ARROW = re.compile(r'(<)?(={2,})\s+(.+?)\s+(={2,})(>?)')

_RE_DOTTED_BARE = re.compile(r'(<)?(-\.+-)(>|x|o)?')
_RE_THICK_BARE = re.compile(r'(<)?(={2,})(>?)')
_RE_SOLID_BARE = re.compile(r'(<|x|o)?(-{2,})(>|x|o)?')

_RE_PIPE_LABEL = re.compile(r'^\|([^|]*)\|')

def _interpret_heads(lh: str, rh: str) -> tuple[str | None, str]:
    """(left_head_char, right_head_char) → (head_glyph, direction)."""
    def head_kind(c: str) -> str | None:
        return {"": None, ">": "arrow", "<": "arrow",
                "x": "cross", "o": "circle"}.get(c)

    lhk = head_kind(lh or "")
    rhk = head_kind(rh or "")
    if lhk and rhk:
        direction = "both"
    elif rhk:
        direction = "right"
    elif lhk:
        direction = "left"
    else:
        direction = "none"
    head = rhk or lhk
    return head, direction

# ─── Main parser ──────────────────────────────────────────────────────

def parse_flowchart(text: str) -> dict:
    """Parse Mermaid flowchart/graph source into a structured dict."""
    direction = "TB"
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    subgraphs: list[dict] = []
    class_defs: list[dict] = []
    link_styles: list[dict] = []
    subgraph_stack: list[dict] = []

    def _new_node(node_id: str) -> dict:
        return nodes.setdefault(node_id, {
            "id": node_id, "label": "", "shape": "default", "classes": [],
        })

    def _track(node_id: str) -> None:
        if subgraph_stack:
            sg = subgraph_stack[-1]
            if node_id not in sg["node_ids"]:
                sg["node_ids"].append(node_id)

    def _parse_at_brace_attrs(attrs_str: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for kv in re.findall(r'([A-Za-z_-]+)\s*:\s*("[^"]*"|[^,]+)', attrs_str):
            k, v = kv
            v = v.strip()
            if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            out[k.strip()] = v
        return out

    def _record_node(spec: str) -> str | None:
        spec = spec.strip()
        if not spec:
            return None

        m_at = _AT_BRACE_RE.match(spec)
        if m_at:
            node_id = m_at.group(1)
            attrs = _parse_at_brace_attrs(m_at.group(2))
            cur = _new_node(node_id)
            if "shape" in attrs:
                cur["shape"] = attrs["shape"]
            if "label" in attrs:
                cur["label"] = attrs["label"]
            _track(node_id)
            return node_id

        m_flag = _NODE_FLAG_RE.match(spec)
        if m_flag:
            node_id = m_flag.group(1)
            label = (m_flag.group(2) or "").strip()
            classes_csv = m_flag.group(3)
            cur = _new_node(node_id)
            cur["shape"] = "asymmetric"
            if label:
                cur["label"] = label
            if classes_csv:
                for c in classes_csv.split(","):
                    if c and c not in cur["classes"]:
                        cur["classes"].append(c)
            _track(node_id)
            return node_id

        m = _NODE_QUOTED_RE.match(spec) or _NODE_RE.match(spec)
        if m:
            node_id = m.group(1)
            open_d, label, close_d = m.group(2), m.group(3), m.group(4)
            classes_csv = m.group(5)
            shape = _SHAPE_MAP.get((open_d, close_d), "default")
            label = label.strip()
            if len(label) >= 2 and label.startswith('"') and label.endswith('"'):
                label = label[1:-1]
            cur = _new_node(node_id)
            if label:
                cur["label"] = label
            if shape != "default":
                cur["shape"] = shape
            if classes_csv:
                for c in classes_csv.split(","):
                    if c and c not in cur["classes"]:
                        cur["classes"].append(c)
            _track(node_id)
            return node_id

        m2 = _BARE_RE.match(spec)
        if m2:
            node_id = m2.group(1)
            cur = _new_node(node_id)
            classes_csv = m2.group(2)
            if classes_csv:
                for c in classes_csv.split(","):
                    if c and c not in cur["classes"]:
                        cur["classes"].append(c)
            _track(node_id)
            return node_id

        return None

    def _split_amp(side: str) -> list[str]:
        return [p.strip() for p in side.split("&") if p.strip()]

    def _emit(srcs: list[str], dsts: list[str], meta: dict) -> None:
        for src in srcs:
            sid = _record_node(src)
            if not sid:
                continue
            for dst in dsts:
                did = _record_node(dst)
                if not did:
                    continue
                edges.append({"from": sid, "to": did, **meta})

    def _find_edge(line: str) -> tuple[int, int, dict] | None:
        # Labeled forms (label captured inside arrow body)
        for rx, base_style in [
            (_RE_DOTTED_LABEL_ARROW, "dotted"),
            (_RE_THICK_LABEL_ARROW,  "thick"),
            (_RE_SOLID_LABEL_ARROW,  "solid"),
        ]:
            m = rx.search(line)
            if not m:
                continue
            if base_style == "dotted":
                lh, label, rh = m.group(1) or "", m.group(2), m.group(3) or ""
                dash_count = 2
            elif base_style == "thick":
                lh, e1, label, e2, rh = (m.group(1) or "", m.group(2),
                                          m.group(3), m.group(4),
                                          m.group(5) or "")
                dash_count = max(len(e1), len(e2))
            else:
                lh, d1, label, d2, rh = (m.group(1) or "", m.group(2),
                                          m.group(3), m.group(4),
                                          m.group(5) or "")
                dash_count = max(len(d1), len(d2))
            head, dirn = _interpret_heads(lh, rh)
            return (m.start(), m.end(), {
                "label": label, "style": base_style,
                "arrow": head is not None,
                "head": head, "direction": dirn,
                "length": max(0, dash_count - 2),
            })

        # Unlabeled forms
        for rx, base_style in [
            (_RE_DOTTED_BARE, "dotted"),
            (_RE_THICK_BARE,  "thick"),
            (_RE_SOLID_BARE,  "solid"),
        ]:
            m = rx.search(line)
            if not m:
                continue
            lh = m.group(1) or ""
            body = m.group(2)
            rh = m.group(3) or ""
            if base_style == "dotted":
                dash_count = 2
            else:
                dash_count = len(body)
            # Reject `--` alone with no head (not a real edge)
            if base_style == "solid" and dash_count == 2 and not lh and not rh:
                continue
            head, dirn = _interpret_heads(lh, rh)
            consumed = m.end()
            label = ""
            after = line[m.end():].lstrip()
            pm = _RE_PIPE_LABEL.match(after)
            if pm:
                label = pm.group(1)
                consumed = m.end() + (len(line[m.end():]) - len(after)) + pm.end()
            return (m.start(), consumed, {
                "label": label, "style": base_style,
                "arrow": head is not None,
                "head": head, "direction": dirn,
                "length": max(0, dash_count - 2),
            })
        return None

    def _parse_edge_line(line: str) -> bool:
        result = _find_edge(line)
        if not result:
            return False
        start, end, meta = result
        src_side = line[:start].strip()
        dst_side = line[end:].strip()
        src_specs = _split_amp(src_side) if "&" in src_side else [src_side]
        dst_specs = _split_amp(dst_side) if "&" in dst_side else [dst_side]
        _emit(src_specs, dst_specs, meta)
        return True

    # ─── Line dispatcher ─────────────────────────────────────────────

    for raw in text.splitlines():
        stripped_raw = raw.strip()
        if _RE_INIT.match(stripped_raw):
            continue
        line = raw.split("%%", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if _RE_END.match(stripped):
            if subgraph_stack:
                subgraph_stack.pop()
            continue

        m = _RE_FLOWCHART.match(stripped)
        if m:
            if m.group(1):
                direction = m.group(1)
            continue

        m = _RE_CLASSDEF.match(stripped)
        if m:
            name, style_str = m.group(1), m.group(2)
            style: dict[str, str] = {}
            for pair in style_str.split(","):
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    style[k.strip()] = v.strip()
            class_defs.append({"name": name, "style": style})
            continue

        m = _RE_CLASS_STMT.match(stripped)
        if m:
            ids_csv, cls_name = m.group(1), m.group(2)
            for nid in [s.strip() for s in ids_csv.split(",") if s.strip()]:
                cur = _new_node(nid)
                if cls_name not in cur["classes"]:
                    cur["classes"].append(cls_name)
            continue

        m = _RE_STYLE.match(stripped)
        if m:
            nid, style_str = m.group(1), m.group(2)
            cur = _new_node(nid)
            style = cur.setdefault("style", {})
            for pair in style_str.split(","):
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    style[k.strip()] = v.strip()
            continue

        m = _RE_LINKSTYLE.match(stripped)
        if m:
            target_str, style_str = m.group(1), m.group(2)
            target: int | str = "default" if target_str == "default" \
                                 else int(target_str.split(",")[0])
            style = {}
            for pair in style_str.split(","):
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    style[k.strip()] = v.strip()
            link_styles.append({"target": target, "style": style})
            continue

        m = _RE_CLICK.match(stripped)
        if m:
            nid = m.group(1)
            target_v = m.group(2) or m.group(3)
            tooltip = m.group(4)
            cur = _new_node(nid)
            click_d = {"target": target_v}
            if tooltip:
                click_d["tooltip"] = tooltip
            cur["click"] = click_d
            continue

        m = _RE_SUBGRAPH.match(stripped) or _RE_SUBGRAPH_QUOTED.match(stripped)
        if m:
            parent_id = subgraph_stack[-1]["id"] if subgraph_stack else None
            if _RE_SUBGRAPH_QUOTED.match(stripped):
                sg = {"id": m.group(1), "label": m.group(1),
                      "direction": None, "node_ids": [],
                      "parent_id": parent_id}
            else:
                sg = {"id": m.group(1), "label": m.group(2) or "",
                      "direction": None, "node_ids": [],
                      "parent_id": parent_id}
            subgraphs.append(sg)
            subgraph_stack.append(sg)
            continue

        m = _RE_DIRECTION.match(stripped)
        if m and subgraph_stack:
            subgraph_stack[-1]["direction"] = m.group(1)
            continue

        if not _parse_edge_line(stripped):
            _record_node(stripped)

    return {
        "direction":   direction,
        "nodes":       list(nodes.values()),
        "edges":       edges,
        "subgraphs":   subgraphs,
        "class_defs":  class_defs,
        "link_styles": link_styles,
    }

# ─── CLI ──────────────────────────────────────────────────────────────

def _load_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="mermaid_parse",
        description="Parse Mermaid flowchart source into structured JSON.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("parse", help="Emit parsed JSON envelope.")
    pa.add_argument("path", nargs="?", default=None,
                     help="Path to mermaid file. Default: read stdin.")

    vl = sub.add_parser("validate",
                          help="Parse + flag orphan edges.")
    vl.add_argument("path", nargs="?", default=None)

    nd = sub.add_parser("nodes", help="List node IDs (one per line).")
    nd.add_argument("path", nargs="?", default=None)

    args = p.parse_args(argv)
    text = _load_text(args.path)
    result = parse_flowchart(text)

    if args.cmd == "parse":
        print(json.dumps(result, indent=2))
        return 0
    if args.cmd == "validate":
        node_ids = {n["id"] for n in result["nodes"]}
        edge_refs: set[str] = set()
        for e in result["edges"]:
            edge_refs.add(e["from"])
            edge_refs.add(e["to"])
        orphans = sorted(edge_refs - node_ids)
        if orphans:
            print(f"warning: edge references undefined nodes: {orphans}",
                  file=sys.stderr)
            return 1
        print(
            f"  ✓ valid: {len(node_ids)} nodes, {len(result['edges'])} edges, "
            f"{len(result['subgraphs'])} subgraphs, "
            f"{len(result['class_defs'])} class_defs, "
            f"{len(result['link_styles'])} link_styles"
        )
        return 0
    if args.cmd == "nodes":
        for n in result["nodes"]:
            print(n["id"])
        return 0
    return 2

if __name__ == "__main__":
    sys.exit(main())
