---
name: behaviour-config
description: Use when configuring kaizen's gate behaviour via brain-sourced rules — deletion allowlists, check-severity overrides, custom-pattern checks. Rules live as brain Notes (under `<KAIZEN_BRAIN_DIR>/Notes/`) with a `kaizen:` frontmatter block. Triggers on "kaizen rule", "brain rule", "deletion allowlist", "kaizen severity override", "custom pattern check", "skip paired-test", "allow git rm in", "block commits containing", "configure kaizen", "behaviour rule", "/kaizen:rule".
version: 1.0.0
---

# kaizen behaviour-config — brain-sourced runtime rules

The kaizen pre-commit gate has a fixed surface (10 checks documented in the `kaizen:workflow` skill PART 3). Users customize that behaviour via **brain-sourced rules** — Markdown notes in `<KAIZEN_BRAIN_DIR>/Notes/` (default `~/.claude/.kaizen/brain/Notes/`) with a `kaizen:` block in their YAML frontmatter. The kaizen plugin owns the storage end-to-end (post-Remember-retirement).

## Why brain-sourced?

| Alternative | Problem |
|---|---|
| `.kaizen.toml` per-project | Doesn't survive across projects; user has to repeat settings |
| Environment variables | Doesn't survive across sessions; have to be set in every shell |
| Plugin-local config file | Plugin-local config sprawl; updates overwrite user settings |
| **Brain notes** ✓ | Owned by the user (in `<KAIZEN_BRAIN_DIR>/Notes/`), cross-project + cross-session, single source of truth |

This is the natural fit: kaizen rules are **personal preferences** about how strict the gate should be. The kaizen Second Brain already exists to hold personal preferences. Eat its own dogfood.

## Rule schema (general shape)

Every kaizen rule lives in a brain note at `~/.claude/.kaizen/brain/Notes/<slug>.md`:

```yaml
---
name: <slug>                  # required — unique identifier
description: <one-line>       # required — human-readable
type: behaviour               # follows Remember's epistemic-type convention
tags: [kaizen, <subtags>]     # tag with `kaizen` so kaizen-brain can find them
sources_count: 1
freshness: stable
created: YYYY-MM-DD
updated: YYYY-MM-DD
kaizen:
  rule_type: deletion-allow | check-severity | custom-pattern
  # … rule-type-specific fields below
---

# <Body — markdown rationale; agent-readable; plugin ignores>

Why this rule exists, what motivated it, links to discussion, etc.
```

The plugin reads only the `kaizen:` frontmatter block. The body is for humans + agent context.

## Three rule types

### 1. `deletion-allow` — whitelist `git rm` paths

Bypass the pre-deletion gate (Check #5) for matching paths, without requiring `KAIZEN_ALLOW_DELETE=1`.

```yaml
kaizen:
  rule_type: deletion-allow
  path_glob: "tests/fixtures/**"      # fnmatch syntax
```

Use cases:
- Test fixtures (regenerable, churn freely)
- Generated artifacts (`build/`, `target/`, `dist/`)
- Stale assets the user routinely cleans up
- Cache directories

The pre-deletion gate scans staged deletions. If ALL of them match `deletion-allow` rules, the gate passes silently. Mixed-allowlist commits (some deletions allowed, some not) still trigger the gate for the non-allowed ones.

### 2. `check-severity` — override a gate check's severity

Re-tune any of the 10 gate checks:

```yaml
kaizen:
  rule_type: check-severity
  check_id: paired-test                # see check IDs below
  severity: skip                        # skip | warn | block
```

| check_id | Default | Description |
|---|---|---|
| `compile-barrier` | block | Compile cmd from `.kaizen.toml` |
| `conventional-commits` | block | Prefix regex |
| `structural-progress-row` | block | Architecture log row demanded |
| `plan-checkbox-tick` | block | Plan-mention → tick |
| `pre-deletion` | block | `git rm` → belief scan |
| `claude-md-no-sha` | block | Rulebook stays clean |
| `paired-test` | warn | New code → paired test |
| `project-verify` | per-project | `verify_cmd` from config |
| `secret-detection` | block | API keys / private keys regex |
| `backlog-drift` | block | `.md` matches `.json` |

Severity values:
- `skip` — don't run the check at all
- `warn` — soft warning, doesn't block commit
- `block` — hard fail, blocks commit until fixed

### 3. `custom-pattern` — run a regex over the staged diff

Add a new check the gate doesn't have:

```yaml
kaizen:
  rule_type: custom-pattern
  pattern_regex: "^\\+.*(TODO|FIXME|XXX):"
  pattern_action: warn                  # warn | block
  pattern_message: "Fresh TODO/FIXME introduced — file an issue or resolve."
```

Pattern runs against `git diff --cached` output. Matches anywhere in the diff. Use `^\+` to scope to added lines only.

Examples:
- `^\+.*console\.log\(` — block stray debug logs
- `^\+.*\.unwrap\(\)` — warn on Rust panic potential
- `password\s*=\s*['\"]` — block hardcoded passwords
- `\bdbg!\s*\(` — block leftover Rust dbg! macros

## Authoring workflow

```
1. kaizen-rules template deletion-allow > /tmp/new-rule.md
   (then edit /tmp/new-rule.md to taste)

2. cp /tmp/new-rule.md ~/.claude/.kaizen/brain/Notes/kaizen-<name>.md

3. kaizen-rules validate
   → ✓ all N rules valid

4. kaizen-rules list
   → see your new rule alongside the others

5. (next commit) the gate consults the rule automatically
```

Or via `kaizen-brain capture "<text>"` if the rule is also a stated preference worth capturing as belief evidence.

## Disabling a rule

Same trick as `kaizen-disable-dupes`: rename the file.

```bash
mv ~/.claude/.kaizen/brain/Notes/<rule>.md ~/.claude/.kaizen/brain/Notes/<rule>.md.disabled
```

The plugin's rule scanner skips `.disabled` files. Reverse the rename to re-enable. Files stay in place; one rename is the full state transition.

## Schema validation

```bash
kaizen-rules validate
```

Catches:
- `rule_type` not in `{deletion-allow, check-severity, custom-pattern}`
- `deletion-allow` missing `path_glob`
- `check-severity` missing `check_id` or invalid `severity`
- `custom-pattern` missing `pattern_regex` / invalid regex syntax / missing `pattern_action`

Run as part of CI if you commit your brain to a git repo.

## Examples (real, useful)

### Allow log file deletions globally

```yaml
---
name: kaizen-allow-log-deletions
description: Allow `git rm` of *.log files anywhere — they're transient.
type: behaviour
tags: [kaizen, deletion-allow]
created: 2026-05-11
kaizen:
  rule_type: deletion-allow
  path_glob: "**/*.log"
---
```

### Demote paired-test to skip on solo projects

```yaml
---
name: kaizen-skip-paired-test
description: Solo project — I write tests after impl lands; the soft warn is noise.
type: behaviour
tags: [kaizen, check-severity]
created: 2026-05-11
kaizen:
  rule_type: check-severity
  check_id: paired-test
  severity: skip
---
```

### Block fresh console.log in JavaScript

```yaml
---
name: kaizen-block-console-log
description: console.log shouldn't survive commits to main.
type: behaviour
tags: [kaizen, custom-pattern, js]
created: 2026-05-11
kaizen:
  rule_type: custom-pattern
  pattern_regex: "^\\+.*console\\.log\\("
  pattern_action: block
  pattern_message: "console.log() in staged diff — strip or convert to proper logging."
---
```

## How the plugin reads rules

Three integration points in `pre-commit.sh`:

1. **Check #5 (pre-deletion gate)** consults `rules.py deletion-allowed <path>` per staged deletion. If all deletions are allowlisted, the belief scan is skipped.
2. **All check severities** consult `rules.py severity <check_id>` before deciding hard/soft/skip behaviour. Brain rules override the default.
3. **Check #11 (custom patterns)** runs `rules.py custom-patterns`, iterates each, runs regex against `git diff --cached`, emits warn or block per pattern_action.

Refresh is automatic — the scripts re-scan brain Notes on every commit. No caching, no restart needed. (For large brains this is ~ms; fine for the gate's <500ms budget.)

## Iron Laws

- **Rules are user preferences, not project state.** They belong in the user's brain, not the project's `.kaizen.toml`.
- **One rule, one file.** Don't pack multiple rules into one note. Easier to disable individually, easier to git-log.
- **Always include `tags: [kaizen, ...]`** so `kaizen-brain audit` can route them correctly.
- **Validate before committing brain changes** — a malformed rule silently disables itself (`validate_rule` returns errors; plugin skips invalid rules). Catch them early.
- **The body matters.** The `# Why` section in each note is the agent-visible rationale for the rule. Future-you will appreciate it.
