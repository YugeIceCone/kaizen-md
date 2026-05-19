---
name: karpathy-check
description: "Karpathy 4-principle review on staged changes (or --last-commit). Checks complexity, diff noise, hidden assumptions, goal verification."
---

# /karpathy-check

Review your staged changes (or last commit) against Karpathy's 4 coding principles.

## Usage

```
/karpathy-check                 # review staged changes
/karpathy-check --last-commit   # review the most recent commit
```

## What it runs

1. **Principle #2 (Simplicity):** `scripts/complexity_checker.py` on all changed files — detects over-engineering, premature abstractions, deep nesting, long functions
2. **Principle #3 (Surgical):** `scripts/diff_surgeon.py` on the diff — detects comment-only changes, whitespace noise, style drift, drive-by refactors
3. **Principles #1 + #4 (Think + Goals):** The `kaizen-karpathy-reviewer` agent reads the diff and applies human-judgment checks — hidden assumptions, missing verification

## Output

A structured report with per-principle verdicts and specific line-level fix recommendations.

## When to run

- Before committing (catches noise and overcomplication early)
- After completing a feature (sanity check before PR)
- When you suspect the LLM overcoded something

## Sub-agent

Dispatches the `kaizen-karpathy-reviewer` agent via the Task tool. See `agents/kaizen-karpathy-reviewer.md`.

## Scripts

- `skills/karpathy/scripts/complexity_checker.py`
- `skills/karpathy/scripts/diff_surgeon.py`
- `skills/karpathy/scripts/assumption_linter.py`
- `skills/karpathy/scripts/goal_verifier.py`

## Skill reference

→ `skills/karpathy/SKILL.md` (or invoke `kaizen:karpathy` via the Skill tool)
