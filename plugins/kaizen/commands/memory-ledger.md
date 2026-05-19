---
name: memory-ledger
description: "Catalog + status + flow over every memory and continuity-of-session surface in kaizen (brain / backlog / handoff / gold / dxm / trace / inbox / chatlog / CLAUDE.md). Verbs - catalog | status | flow. Triggers - 'memory ledger', 'where does memory live', 'memory surfaces', 'continuity flow', 'project vs global state'."
argument-hint: "[catalog | status | flow] [--json]"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-memory-ledger:*)"]
---

# /kaizen:memory-ledger

!`bash -c 'exec ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-memory-ledger ${ARGUMENTS:-catalog}'`

## Verbs

| Verb | Use |
|---|---|
| `catalog [--json]` | Print every declared surface — name / owner / scope / path / auto-load. Read-only. |
| `status [--json]`  | Sample each surface on disk: exists? Missing-when-declared = warn finding. |
| `flow [--json]`    | Walk the continuity-of-session flow phase-by-phase (session_start → between_sessions). |

Default verb (no args) is `catalog` — the quickest "what surfaces does this plugin manage" overview.

## Why a ledger?

Memory + continuity surfaces grew across 9 owner features (brain,
better-memory, backlog, handoff, gold, dxm, trace, inbox, chatlog).
The ledger is the single point of truth for **where memory lives**
and **how continuity flows**. Owner CLIs still handle reads/writes;
the ledger is observability-only.

## Scope discipline

Every surface declares `scope: project | global`. The manifest is the
data future scope-discipline lints will walk (BK-024, ML-005, ML-006).

## Manifest

Source of truth: `skills/memory-ledger/domain/memory-surfaces.yaml`.
Add a new surface there before shipping a feature that persists state.

## Bypass

```
export KAIZEN_MEMORY_LEDGER_DISABLE=1
```

Every verb becomes a silent no-op.

## Folded surface (formerly separate slashes)

Four memory + continuity slashes absorbed in consolidate-2 D5; bins / skills / databases remain reachable and continue to be the canonical capture/inspect verbs. **This is a menu-UX collapse, not a behaviour change — handoff store, brain DB, gold log, and backlog json all stay intact:**

| Concern | Bin (direct) | Use case |
|---|---|---|
| Durable second brain | `kaizen-brain` | capture / search / promote / audit / evolve / show / append — was `/kaizen:brain` |
| Mid-work pattern capture | `kaizen-gold` | capture / list / show / promote / path — was `/kaizen:gold` |
| Session-boundary continuity | `kaizen-handoff` | create / resume / verify / assess / auto-finalize / bridge / latest — was `/kaizen:handoff` |
| Active work tracker | `kaizen-backlog` | list / add / start / tick / done / park / unpark / decision / render / verify / show — was `/kaizen:backlog` |

All four are already declared surfaces in
`skills/memory-ledger/domain/memory-surfaces.yaml`; this fold puts the
verb invocation alongside the catalog instead of in a separate slash.
