---
created: 2026-05-12
updated: 2026-05-12
type: belief
confidence: 0.97
tags: [preference, formatting, response-style, communication]
sources_count: 2
freshness: hardened
evidence:
  - source: Journal/2026-05-12.md
    quote: "please dont use tables"
    date: 2026-05-12
    context: "After several recent responses heavy with markdown tables (capability matrices, trigger lists, file-location maps, comparison grids), user explicitly asked me to stop. Direct preference, no qualifier."
  - source: Journal/2026-05-12.md (audit-recap entry)
    quote: "regression — table overuse across the rest of the session despite the rule being created today"
    date: 2026-05-12
    context: "Self-audit at session end confirmed I created the rule + then violated it ~30 times in the same session. Rule needs ACTIVE recall on each response, not just passive availability in the brain."

---

# No markdown tables in responses

**Rule**: Do not use markdown tables (`| col | col |` syntax) in user-facing responses. Use bullet lists, prose with inline labels, or definition-list-style indented pairs instead.

**Why**: User finds them visually noisy / hard to scan in the terminal-style UI they're working in, or simply prefers continuous prose for technical exchange. Either way it's a stable presentation preference — applies cross-project, cross-session.

**How to apply**:

- Replace `| key | value |` with `**key** — value` on its own line, or a bulleted list of `- **key**: value`.
- Replace comparison tables with side-by-side bullet sections.
- For sequences with multiple fields per row (e.g. "tool / purpose / output"), use one bullet per item, fields separated by ` — ` or newlines.
- Code blocks, CLI invocations, and JSON shapes are NOT tables and stay welcome.
- File trees, ASCII diagrams, and indented hierarchies are NOT tables and stay welcome.

**Examples**:

Wrong:
```
| Skill | Trigger |
|---|---|
| kaizen:tdd | new code |
| kaizen:solid | refactoring |
```

Right:
- `kaizen:tdd` — new code
- `kaizen:solid` — refactoring

Or as flowing prose: "Load `kaizen:tdd` for net-new code, `kaizen:solid` when refactoring."

**Scope**: Applies to ANY response in the chat conversation. Documents I write (CHANGELOGs, SKILL.md frontmatter docs, README sections) MAY use tables when authoring durable artifacts — those are read in different contexts. If unsure, ask. Default for the chat surface: no tables.

**Related**:
- [[pref-handoff-over-raw-log]] — terse, scan-friendly communication preference (also applies)
- General terseness pattern from Evidence Log: "yes", "yes continue", "go" — action-oriented brevity. No tables fits the same shape: less visual ceremony, more substance per line.
