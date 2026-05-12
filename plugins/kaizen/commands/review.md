---
name: review
description: Fast diff-time code review (per the article's "code review" definition). Runs against the current diff (HEAD vs base; staged if HEAD is clean). Lightweight, frequent, peer-style. Catches logic-error patterns, coding-skill violations, paired-test gaps, style drift, minor security smells. Pair with /kaizen:audit for periodic deep-dive.
---

# kaizen review

Per-change code review. Per [synavos: Code Review vs Code Audit](https://synavos.com/blogs/code-review-vs-code-audit/) — **review is per-change, lightweight, peer-style, immediate-feedback**. Distinct from `/kaizen:audit` (periodic + comprehensive + severity-classified).

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/review.sh ${ARGUMENTS}`

## Subcommands / flags

| Flag                   | Effect                                                       |
|------------------------|--------------------------------------------------------------|
| (none)                 | Review HEAD vs `main`/`master`/`HEAD~1`. Inline-style output. |
| `--base <ref>`         | Compare against an explicit ref.                             |
| `--staged`             | Review `git diff --cached` only.                             |
| `--agent`              | Also dispatch the `agent-critic` subagent for a deeper pass. |
| `--json`               | Emit findings as JSON (for CI consumption).                  |

## What it catches

- **Paired-test gap** — new `pub fn` / `export function` / `def` without matching tests.
- **Deep nesting hot-spot** — added lines indented ≥16 spaces (KISS smell).
- **TODO/FIXME/XXX/HACK** markers introduced in this diff.
- **Long-function smell** — single hunks > 80 added lines (SoC nudge).
- **Hardcoded secrets** — `api_key/secret/password/token = "<literal>"` patterns.
- **Diff size** — >15 files triggers the kaizen sizing advisory.
- **Style drift** — trailing whitespace, plus a reminder to run the configured compile-barrier.

Output is grouped by marker: `!` warnings (block-worthy), `~` smells (advisory), `i` info.

## What it does NOT do

- No deep architecture analysis — that's `/kaizen:audit`.
- No security threat modeling — that's `/kaizen:audit` or the `agent-aegis` skill.
- No system-wide compliance check — `/kaizen:audit`.
- No state mutation — purely read-only. Run as often as you like.

## When to use which

| Situation                                          | Tool                |
|----------------------------------------------------|---------------------|
| About to open a PR / merge a branch                | `/kaizen:review`    |
| Pre-commit gate (staged diff)                      | `/kaizen:gate`      |
| AI-generated code, need discipline checklist       | `/kaizen:vibe-check`|
| Before a major release / quarterly check / audit   | `/kaizen:audit`     |
| Suspected security issue                           | `agent-aegis` skill |
| Sweeping refactor planning                         | `/workflow` skill   |

## Agent dispatch (`--agent`)

When `--agent` is passed, the script emits a hint that the slash command body should invoke the `agent-critic` subagent. Claude follows up with a smarter pass — covering nuances the regex-based checks miss (intent, naming, hidden coupling).

Example: `/kaizen:review --agent`

## Examples

```
/kaizen:review                       # default: HEAD vs main, inline output
/kaizen:review --staged              # just the staged diff
/kaizen:review --base develop        # against the develop branch
/kaizen:review --json                # machine-readable for CI
/kaizen:review --agent --base main   # full agent-driven review of the branch
```

## Companion

- `/kaizen:audit` — the deep-dive sibling. Run periodically (release boundaries, monthly, before major refactors).
- `/kaizen:gate` — the commit-time enforcer (mostly the same checks but with block semantics).
- `/kaizen:vibe-check` — AI-discipline overlay for AI-authored diffs.
