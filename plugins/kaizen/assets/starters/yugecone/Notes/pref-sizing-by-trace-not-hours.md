---
name: Size work by trace + sem + grep, not by hours
description: Don't grade or scope work in clock-time (hours/minutes). Scope by tracing the blast radius (call-graph reach, reverse-deps, cross-context hops) and counting concrete grep/sem-search hits. Thresholds are file-count and structural, not temporal.
type: belief
confidence: 0.95
tags: [preference, workflow, planning, sizing, scoping, blast-radius]
sources_count: 1
freshness: stable
created: 2026-05-11
updated: 2026-05-11
---

# Size work by trace + sem + grep, not by hours

When estimating whether a work item is small/medium/large, or whether
to promote a micro item to a real plan file, **do not use clock-time
(hours, minutes, days)**. Time-based estimates lie — a "5-minute fix"
hides cycle-traps; an "8-hour refactor" is actually three files. Use
**measurable blast radius** instead:

- `grep -rE "<symbol|file|concept>" --include='*.<lang>' | wc -l` → file-hit count
- `cargo tree -p <crate> -e all -i` (or language equivalent) → reverse-dep count
- `ast-grep` or `llm-tldr-deep` on the touched function/trait → caller + callee graph
- `git grep -l` across canonical-source dirs (e.g. `port/<project>3` for this workspace) → convergence check
- Cross-context hops (count crates / packages / bounded contexts touched)
- Cargo.toml / package.json / go.mod edits (any structural manifest change is its own signal)
- Trait/interface moves between layers (Onion port shifts)

## Thresholds (concrete, not durational)

| Probe result | Action |
|---|---|
| ≤3 files touched, 0 Cargo.toml edits, 0 trait moves, single bounded context | stays micro, single checkbox |
| 4–15 files OR 1 Cargo.toml OR 1 trait move | split into 2–4 sibling micro items |
| ≥16 files OR ≥2 Cargo.toml OR cross-context OR carve-out triggered (dynamic-LOC rule) | promote to `plans/<date>-<slug>.md` with phases |
| Probe fails to converge (sem search no canonical hit, traces hit cycles) | park with the failing probe noted; surface as a question |

## How to apply

- **Run the probe BEFORE picking up an item.** Probe takes seconds; the
  cost of wrong-sized work is hours.
- **Trust the probe over intuition.** If a "trivial" item touches 14
  files, it is not trivial.
- **Re-probe on surprise.** If actual file-hits exceed the predicted
  count by 2× mid-work, stop and re-classify; either split or promote.
- **Record the probe** when it justifies a promotion. The plan file's
  "Risk register" section starts with the probe output as evidence.

## Why

- Hours are subjective and context-dependent; file counts are not.
- The cycle-trap (a "small change" that touches three Cargo.tomls and
  inverts a dep arrow) is invisible to clock-time estimates but
  obvious to `cargo tree -i`.
- Probes are cheap and re-runnable; estimates are not.

## Evidence

- source: Journal/2026-05-11.md
  quote: "don't grade work in hours you trace and sem+grep to scope the size"
  date: 2026-05-11
