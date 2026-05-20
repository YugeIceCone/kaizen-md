# Plan: merge auto-handoff into handoff

## Status

**DRAFT 2026-05-20** — fold the auto-handoff skill + bin + schemas
into the handoff skill. After this plan, "auto-handoff" is no longer a
separate top-level concept — it's the threshold-triggered subcommand
of `handoff`.

## Goal

Today there are TWO sibling concepts:

- **handoff** — user-triggered: `kaizen-handoff create|resume|...`
  - skills/handoff/SKILL.md
  - schemas/handoff/{handoff,outcome-rubric,verify-rules}.yaml
  - scripts/handoff/handoff.py + _handoff.py + _session_jsonl.py
  - bin/kaizen-handoff
- **auto-handoff** — threshold-triggered (Stop-hook `decision=block`)
  - skills/auto-handoff/SKILL.md
  - schemas/auto-handoff/{config,rubric}.yaml + schemas/
  - scripts/handoff/auto_handoff.py
  - bin/kaizen-auto-handoff
  - hooks/claude/auto-handoff.sh

Auto-handoff is really "handoff with a threshold trigger" — a
sub-mode, not a separate feature. Merging:

- collapses two SKILL.md surfaces into one (less for the agent to
  load)
- moves config + rubric into the handoff skill's schema dir
- keeps the existing `kaizen-handoff` bin + adds a `kaizen-handoff
  auto-check` subcommand to replace `kaizen-auto-handoff`
- preserves the Stop-hook contract (the script still exists; just the
  CLI entry point changes)

## Current state

```
skills/auto-handoff/SKILL.md                (~150 LOC — body)
skills/handoff/SKILL.md                     (~main skill body)
skills/handoff/agents/                      (agent interface yamls)

schemas/auto-handoff/
├── config.yaml                             (4-threshold config)
├── rubric.yaml                             (decision rubric)
└── schemas/
    └── config.schema.json                  (validates config.yaml)

schemas/handoff/
├── handoff.yaml                            (handoff manifest v2)
├── outcome-rubric.yaml
├── verify-rules.yaml
└── schemas/                                (handoff JSON Schemas)

scripts/handoff/
├── _handoff.py                             (shared helpers)
├── _session_jsonl.py                       (session log reader)
├── auto_handoff.py                         (threshold check + emit)
└── handoff.py                              (consolidated CLI)

bin/
├── kaizen-handoff                          (-> scripts/handoff/handoff.py)
└── kaizen-auto-handoff                     (-> scripts/handoff/auto_handoff.py)

hooks/claude/auto-handoff.sh                (Stop-hook calling auto_handoff.py)
.claude-plugin/plugin.json                  (permissions for both bins)
```

## Target state

```
skills/handoff/SKILL.md                     (merged body — describes
                                              both manual + automatic)
skills/handoff/agents/                      (unchanged)

schemas/handoff/
├── handoff.yaml                            (manifest — unchanged)
├── outcome-rubric.yaml                     (unchanged)
├── verify-rules.yaml                       (unchanged)
├── auto-config.yaml                        (← from schemas/auto-handoff/config.yaml,
                                              prefixed to disambiguate)
├── auto-rubric.yaml                        (← from schemas/auto-handoff/rubric.yaml)
└── schemas/
    ├── (existing handoff schemas)
    └── auto-config.schema.json             (← was config.schema.json)

scripts/handoff/                            (unchanged location;
                                              auto_handoff.py keeps
                                              its name as the impl module)

bin/kaizen-handoff                          (unchanged — main CLI)
hooks/claude/auto-handoff.sh                (unchanged — still fires the
                                              auto_handoff.py path)
.claude-plugin/plugin.json                  (drop the kaizen-auto-handoff
                                              entry; the .sh hook stays)
```

The `kaizen-auto-handoff` bin is RETIRED. The Stop-hook path keeps
working because it invokes `python3 .../scripts/handoff/auto_handoff.py`
directly — it never went through the bin.

## Phases

### Phase 1 — Move schemas [x]

- [x] git mv 6 files from schemas/auto-handoff/{config.yaml, rubric.yaml,
      schemas/{config,decision,event,rubric}.schema.json} into
      schemas/handoff/ with auto- prefix
- [x] rmdir schemas/auto-handoff/{schemas,} (empty)
- [x] Updated auto_handoff.py _DEFAULT_CONFIG_PATH + _DEFAULT_RUBRIC_PATH
- [x] Updated auto_handoff.py module docstring
- [x] Updated test_auto_handoff.py (6 path refs) + plugin-development
      references/rubric-pattern.md (1 ref) — test_auto_handoff: 19/19 green

### Phase 2 — Merge skill bodies [x]

- [x] handoff/SKILL.md description front-matter expanded to cover
      both manual + auto modes with full trigger-phrase list
- [x] Appended "## Auto-trigger mode — context-pressure → forced
      handoff" section with full body (contract, config, dedupe,
      bypass, threshold source, implementation pointers)
- [x] Fixed scripts/handoff/auto_handoff.py path reference (was
      pointing at retired skills/workflow/scripts/auto_handoff.py)
- [x] `git rm skills/auto-handoff/SKILL.md` + dir removed

### Phase 3 — Retire kaizen-auto-handoff bin

- [ ] `git rm bin/kaizen-auto-handoff`
- [ ] Remove the auto-handoff bin permission entry from
      .claude-plugin/plugin.json
- [ ] (The .sh hook stays — it calls auto_handoff.py via plugin-root)
- [ ] Update commands/*.md if any reference `kaizen-auto-handoff`
- [ ] Update DEVOPS-CHEAT-SHEET.md + any references docs

### Phase 4 — Optionally expose as a subverb of kaizen-handoff

- [ ] If `kaizen-handoff` is consolidated-CLI (multi-verb), add an
      `auto-check` subverb that calls the same code as the hook
      uses. Keeps a CLI entry point for manual auto-check invocations.
- [ ] Document in SKILL.md + the bin's docstring

Skip if `kaizen-handoff` doesn't already use the multi-verb pattern.

### Phase 5 — Tests + verification

- [ ] Run full `kaizen-tests --concurrency 4` — expect 331/333 (the
      pre-existing baseline)
- [ ] Run `kaizen-health` — clean
- [ ] Run the auto-handoff hook manually with a synthetic event JSON
      to confirm threshold-trigger still works
- [ ] Update test_auto_handoff fixtures to match new paths
- [ ] Update progress.md row

## Invariants

- The Stop-hook `decision=block` contract is preserved — auto-handoff
  is a MODE of handoff, not a removed feature
- `scripts/handoff/auto_handoff.py` keeps its filename + location —
  the hook invokes it by path, not via bin
- No data loss: every config knob in `schemas/auto-handoff/config.yaml`
  carries over to `schemas/handoff/auto-config.yaml` byte-for-byte
- Tests stay green per commit (5 sub-commits expected)

## Rollback

Per-phase commits; `git revert <sha>` undoes any phase. Phase 1
(schema move) is the most likely cause of cascade if auto_handoff.py
caches CONFIG_PATH — verify by running the hook manually before
moving past Phase 1.

## Out of scope

- Renaming auto_handoff.py to something handoff-prefixed (e.g.
  handoff_auto.py). The current name reads cleanly + the module is
  imported by `import auto_handoff` in hooks; renaming creates churn.
- Restructuring the Stop-hook integration. Hook stays as-is.
- Merging the underlying handoff.py + auto_handoff.py modules into
  one file. They share `_handoff.py` helpers already.
