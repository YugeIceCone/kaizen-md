# Tasks — <feature-name>

> Derived from: `design.md` + `requirements.md`
> Status: not started | in progress | done

## Task list

- [ ] **<verb-first task title>**
  - REQ refs: REQ-###, REQ-###
  - Design refs: <component / section in design.md>
  - Files: `<path>`, `<path>`
  - Verify: `<exact CLI command that proves done>`
  - Depends on: <task-id or "none">
  - Estimate: S | M | L

- [ ] **<next task>**
  - REQ refs: REQ-###
  - Files: …
  - Verify: …
  - Depends on: …
  - Estimate: …

## Definition of done

Every task ticked AND every EARS requirement in `requirements.md` exercised by at least one verify command AND `<project compile-barrier cmd>` exits 0.

## Resume protocol

For a fresh agent picking this up:
1. Read `requirements.md` for the EARS requirements.
2. Read `design.md` for the architecture.
3. Read `decisions.md` for non-obvious choices.
4. Find the first unchecked task above; start there. Run its `Verify:` command after each edit.
