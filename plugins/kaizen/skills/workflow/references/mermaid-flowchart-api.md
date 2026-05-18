# Mermaid Flowchart API — complete inventory

Source: context7 `/mermaid-js/mermaid` (v11.x), cross-referenced with
the official docs (`syntax/flowchart.md`). Captured 2026-05-18 for
the kaizen `mermaid_parse.py` parser implementation.

Coverage column: ✓ parsed in v2, ⚠ partial, ✗ not parsed.

## 1. Diagram header

| Syntax | Meaning | Coverage |
|---|---|---|
| `flowchart <DIR>` | flowchart with direction | ✓ |
| `graph <DIR>` | legacy alias for flowchart | ✓ |
| `<DIR>` ∈ `TB` / `TD` / `BT` / `RL` / `LR` | top-bottom / top-down / bottom-top / right-left / left-right; default `TB` | ✓ |
| `%%{init: {...}}%%` | inline config directive | ✗ skipped (treated as comment) |
| `---\nconfig:\n  ...\n---` | YAML frontmatter config | ✗ skipped |

## 2. Node shapes — classic ASCII syntax

| Syntax | Shape name | Coverage |
|---|---|---|
| `A` | default (rect) | ✓ |
| `A[text]` | rect | ✓ |
| `A(text)` | round / stadium | ✓ |
| `A([text])` | stadium (pill) | ✓ |
| `A((text))` | circle | ✓ |
| `A(((text)))` | double circle | ✓ |
| `A[(text)]` | cylinder | ✓ |
| `A[[text]]` | subroutine | ✓ |
| `A{text}` | diamond / rhombus | ✓ |
| `A{{text}}` | hexagon | ✓ |
| `A[/text/]` | parallelogram (right-leaning) | ✓ |
| `A[\text\]` | parallelogram (left-leaning) | ✓ |
| `A[/text\]` | trapezoid | ✓ |
| `A[\text/]` | trapezoid (inverted) | ✓ |
| `A>text]` | asymmetric / flag | ✓ |
| `A["quoted with (special) chars"]` | quoted label — handles `()` `[]` inside | ✓ |

## 3. Node shapes — new `@{...}` syntax (v11+)

| Syntax | Coverage |
|---|---|
| `A@{ shape: <name>, label: <text> }` | ✓ (47 shape names from `flowchart_expanded_node_shapes.html`) |

Recognized shape names (passed through as-is to the `shape` field):
bang · notch-rect · cloud · hourglass · bolt · brace · brace-r · braces · lean-r · lean-l · cyl · diam · delay · h-cyl · lin-cyl · curv-trap · div-rect · doc · rounded · tri · fork · win-pane · f-circ · lin-doc · lin-rect · notch-pent · flip-tri · sl-rect · trap-t · docs · st-rect · odd · flag · hex · trap-b · rect · circle · sm-circ · dbl-circ · fr-circ · bow-rect · fr-rect · cross-circ · tag-doc · tag-rect · stadium · text

## 4. Edge styles — line + arrow

| Syntax | Style | Arrowhead | Coverage |
|---|---|---|---|
| `-->` | solid | right-arrow | ✓ |
| `---` | solid | none | ✓ |
| `<-->` | solid | bidirectional | ✓ |
| `-.->` | dotted | right-arrow | ✓ |
| `-.-` | dotted | none | ✓ |
| `==>` | thick | right-arrow | ✓ |
| `===` | thick | none | ✓ |
| `--x` | solid | cross (right) | ✓ |
| `x--` | solid | cross (left) | ✓ |
| `x--x` | solid | cross (both) | ✓ |
| `--o` | solid | circle (right) | ✓ |
| `o--` | solid | circle (left) | ✓ |
| `o--o` | solid | circle (both) | ✓ |
| `--->`, `---->` (extra dashes) | longer line, same arrow | ✓ (style + arrow extracted; length stored as `length` int) |
| `~~~` | invisible link | ✗ skipped |
| `&==&` (animated) | animated edge | ✗ skipped |

## 5. Edge labels

| Syntax | Coverage |
|---|---|
| `-->|label|` | pipe-style | ✓ |
| `-- label -->` | inline (solid only) | ✓ |
| `-. label .->` | dot-style (dotted only) | ✓ |
| `== label ==>` | thick with label | ✓ |
| `"label"` with backticks for markdown | ⚠ captured as raw text |
| `<br/>` for line breaks | ⚠ captured as-is |
| `fa:fa-icon` FontAwesome | ⚠ captured as-is |

## 6. Multi-node sugar

| Syntax | Coverage |
|---|---|
| `A & B --> C` | one edge per LHS-RHS pair → 2 edges | ✓ |
| `A --> B & C` | one edge per pair → 2 edges | ✓ |
| `A & B --> C & D` | cartesian product → 4 edges | ✓ |

## 7. Subgraphs

| Syntax | Coverage |
|---|---|
| `subgraph ID` ... `end` | ✓ |
| `subgraph ID [Title]` ... `end` | ✓ |
| `subgraph "Quoted Title"` ... `end` | ✓ |
| `direction LR` (inside subgraph) | ✓ |
| Nested subgraphs | ✓ (stack-based; nested subgraphs recorded with ancestor chain in `parent_id`) |

## 8. Styling

| Syntax | Coverage |
|---|---|
| `classDef name fill:#...,stroke:#...,...` | ✓ |
| `A:::name` (single-node assignment) | ✓ |
| `class A,B,C name` (multi-node assignment) | ✓ |
| `style A fill:#...,stroke:#...,...` (per-node) | ✓ |
| `linkStyle 0 stroke:#...,...` (per-edge by index) | ✓ |
| `linkStyle default ...` | ✓ |

## 9. Interactivity

| Syntax | Coverage |
|---|---|
| `click A "url"` | ✓ (captured as `click` per node) |
| `click A "url" "tooltip"` | ✓ |
| `click A callback` (JS callback) | ✓ |
| `click A call cbName(args) "tooltip"` | ⚠ stored as raw |

## 10. Comments

| Syntax | Coverage |
|---|---|
| `%% line comment` | ✓ stripped |
| `%%{init: ...}%%` | ✓ treated as comment (not parsed) |

## Output envelope

```python
{
  "direction":  "TB",
  "nodes": [
    {"id": "A", "label": "...", "shape": "rect", "classes": [...],
     "style": {...},   # set when `style A ...` line present
     "click": {...},   # set when `click A ...` line present
    },
  ],
  "edges": [
    {"from": "A", "to": "B",
     "label":  "...",
     "style":  "solid" | "dotted" | "thick",
     "arrow":  "right" | "left" | "both" | "none",  # was bool in v1
     "head":   "arrow" | "cross" | "circle",
     "length": 1,     # number of dashes - 2 (extra-dash rank spans)
    },
  ],
  "subgraphs": [
    {"id": "G1", "label": "...", "direction": "LR",
     "node_ids": [...], "parent_id": null},
  ],
  "class_defs": [{"name": "...", "style": {prop: value}}],
  "link_styles": [{"target": 0|"default", "style": {prop: value}}],
}
```

## What this parser intentionally does NOT do

- Render the diagram (no SVG / no canvas)
- Validate beyond basic orphan-ref check
- Round-trip edits back to Mermaid source
- Resolve `%%{init: ...}%%` config affecting parse (e.g. `htmlLabels`)

For those, use the official `mermaid-cli` (`mmdc`) or the JS library.
