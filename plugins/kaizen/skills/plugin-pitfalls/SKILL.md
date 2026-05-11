---
name: plugin-pitfalls
description: Use when building, debugging, or publishing a Claude Code plugin. Catalogues 10 real failure modes encountered in production (hooks.json wrapper, slash-command argument routing, /plugin update cache, name shadowing, SSH auth mismatch, cross-platform script portability, etc.) with symptom + cause + fix. Triggers on "plugin won't load", "hook load failed", "slash command runs unexpected", "/plugin update no content", "Repository not found", "ssh-askpass", "readlink -f", "find -printf", "ssh user mismatch", "skill name shadowing", "plugin cache stale", "expected record received undefined", "argument router pattern", "version bump plugin", "publish plugin failure".
version: 1.0.0
---

# Claude Code plugin pitfalls — gotchas catalogue

Every entry below is a real bug encountered while building the `kaizen` plugin. They're not theoretical; each broke a build or hid a real error. Lead with symptom (what the user sees) so the skill activates when the symptom appears in a session.

## ⚠ Read in full before debugging

If you're working on a plugin that "loads but doesn't work", "won't update", "ran the wrong subcommand", or "publishes but pushes fail" — skim every section below. The catalogue is short on purpose. The cross-cutting lesson: **Claude Code's plugin system has a few rigid behaviors documented inconsistently across the docs; failures look like generic shell or git errors but are plugin-system-specific.**

---

## 1. `hooks.json` must be wrapped in a top-level `hooks` record

### Symptom

After installing and reloading, `/doctor` reports:

```
✘ <plugin> (user)
   Failed to load hooks from /path/to/hooks/hooks.json: [
     { expected: "record", code: "invalid_type",
       path: ["hooks"],
       message: "Invalid input: expected record, received undefined" }
   ]
   Check hooks.json file syntax and structure
```

`/reload-plugins` shows `1 error during load. Run /doctor for details.`

### Cause

Many examples (including Anthropic's older docs) show `hooks.json` as a flat object keyed by event name:

```json
{
  "SessionStart": [...],
  "PreToolUse": [...]
}
```

The strict validator in current Claude Code requires a top-level `hooks` wrapper:

```json
{
  "hooks": {
    "SessionStart": [...],
    "PreToolUse": [...]
  }
}
```

### Fix

Wrap the object:

```bash
cat hooks.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
if 'hooks' not in d: d = {'hooks': d}
print(json.dumps(d, indent=2))" > hooks.json.new && mv hooks.json.new hooks.json
```

### Prevention

Pre-publish check: validate that `python3 -c "import json; d=json.load(open('hooks/hooks.json')); assert 'hooks' in d"` passes.

---

## 2. Slash commands evaluate EVERY `` !`...` `` block, not just the matching one

### Symptom

User types `/myplugin:publish` with no args. Instead of showing status, the script runs `publish.sh reset --yes` (destructive) and errors out with a confirmation prompt. Or `/myplugin:backup` errors `restore: missing <id>`.

### Cause

The "argument router" pattern in command markdown:

```markdown
- No args → status:
  !`bash script.sh status`
- `reset` → DESTRUCTIVE:
  !`bash script.sh reset $ARGUMENTS`
- `create` → create remote:
  !`bash script.sh create $ARGUMENTS`
```

…**runs every** `` !`...` `` block on every invocation. The prose conditionals (`No args → status`) are NOT control flow — they're documentation. Claude Code evaluates all the fenced bash blocks regardless of which conditional they sit under.

### Fix

One bash invocation per command. Let the underlying script's case statement handle subcommands. Use shell-default expansion for the empty-args case:

```markdown
!`bash ${CLAUDE_PLUGIN_ROOT}/skills/X/scripts/Y.sh ${ARGUMENTS:-status}`
```

The script's own `case "$cmd"` dispatcher routes by `$ARGUMENTS`. Documentation goes in the prose surrounding the single dispatch line.

### Prevention

```bash
# Pre-publish lint: every command must have exactly one `!` invocation
for f in commands/*.md; do
    n=$(grep -cE '!`(bash|python|node)' "$f")
    [ "$n" -gt 1 ] && echo "BUG: $f has $n bash blocks (only 1 allowed)"
done
```

---

## 3. `/plugin update` silently no-ops without a version bump

### Symptom

Push a bug fix to `origin/master`. Run `/plugin update <plugin>@<marketplace>` — returns `(no content)`. `/reload-plugins` still shows the broken state. Cache stuck at the old commit SHA.

### Cause

`/plugin update` checks `plugin.json:version` and the upstream marketplace's known SHA. If the version field matches the cache copy AND nothing in the marketplace manifest changed, the updater skips the refresh. Same-version commits are treated as no-ops, even when the actual source files differ on disk.

### Fix

Bump `version` in `plugin.json` (semver patch is sufficient for bug fixes):

```bash
sed -i 's/"version": "1.1.0"/"version": "1.1.1"/' plugins/<name>/.claude-plugin/plugin.json
```

Then `/plugin update <name>@<marketplace>` actually refreshes the cache.

### Prevention

For any fix commit that ships behavior changes (not just docs), bump the patch version in the same commit. Treat the version bump as a structural change requirement.

---

## 4. Plugin `name: doctor` (or `help`, `clear`, etc.) shadows Claude Code built-ins

### Symptom

User runs `/doctor` to see plugin load errors. Instead of Claude Code's built-in diagnostic, the plugin's own diagnostic script runs — hiding the real error message. Built-in `/help`, `/clear` etc. similarly shadowable.

### Cause

Claude Code resolves `/X` by checking installed plugin commands before falling back to built-ins. A plugin command with `name: doctor` in its frontmatter intercepts `/doctor`.

### Fix

Rename to avoid built-in collisions. Reserved names (don't use as plugin command `name:`):

- `doctor` — plugin load diagnostic
- `help` — top-level help
- `clear` — clear conversation
- `compact` — compact conversation
- `model` — switch model
- `config` — settings
- `skills` — skill list
- `plugin` — plugin management
- `reload-plugins` — reload plugins

Use plugin-themed alternates: `health`, `info`, `check`, `diagnose`, `setup`, etc.

### Prevention

```bash
RESERVED='doctor help clear compact model config skills plugin reload-plugins'
for f in commands/*.md; do
    name=$(grep -E "^name:" "$f" | head -1 | sed 's/name: //')
    for r in $RESERVED; do
        [ "$name" = "$r" ] && echo "BUG: $f shadows built-in /$r"
    done
done
```

---

## 5. SSH key vs `gh` CLI authentication mismatch

### Symptom

`gh repo create <owner>/<name> --source=. --remote=origin --push` succeeds on the GitHub side but fails on push with:

```
ERROR: Repository not found.
fatal: Could not read from remote repository.
```

OR:

```
ssh_askpass: exec(/usr/bin/ssh-askpass): No such file or directory
Host key verification failed.
```

### Cause

`gh` authenticates with one identity (e.g. `YugeIceCone` via OAuth token), but `git push` over SSH uses whatever SSH key happens to be loaded in your agent — possibly authenticating as a DIFFERENT GitHub user who has no access to the just-created repo. "Repository not found" via SSH means "auth succeeded but the user can't see this repo".

### Fix

Configure git to use `gh`'s credential helper, which routes through HTTPS with the same token gh uses:

```bash
gh auth setup-git
git remote set-url origin https://github.com/<owner>/<name>.git
git push -u --force origin master   # or with the SSH URL — both work via gh helper
```

### Diagnostic

```bash
ssh -T git@github.com           # → "Hi <username>!" — confirms WHICH user SSH sees you as
gh auth status                   # → which user gh sees you as
# If different → you have the mismatch; use gh auth setup-git
```

### Prevention

After `gh auth login` on any new machine, immediately run `gh auth setup-git`. Persistent fix.

---

## 6. `readlink -f` and `find -printf` are GNU-only

### Symptom

Scripts work on Linux, fail silently on macOS. macOS BSD `readlink` doesn't have `-f`; `find -printf` doesn't exist. Cross-platform CI hits this on the `macos-latest` matrix row.

### Cause

Two utilities with same name, different feature sets across Linux GNU coreutils and macOS BSD.

### Fix

For real-path resolution (portable Linux + macOS):

```bash
realpath_f() {
    python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$1"
}

_SCRIPT_REAL_DIR="$(cd "$(dirname "$(realpath_f "${BASH_SOURCE[0]}")")" && pwd)"
```

For `find -printf` (listing basenames or relative paths):

```bash
# Replace: find "$dir" -maxdepth 1 -type d -printf '%f\n'
# With:
for d in "$dir"/*/; do basename "$d"; done
```

### Prevention

Lint shell scripts pre-publish:

```bash
grep -rn 'readlink -f' scripts/ hooks/ && echo "BUG: GNU-only readlink -f"
grep -rn 'find.*-printf' scripts/ hooks/ && echo "BUG: GNU-only find -printf"
```

Add to CI: same grep as a fail-on-match step.

---

## 7. `set -uo pipefail` aborts on unbound vars in fallback branches

### Symptom

Script crashes with `BACKLOG_JSON: unbound variable` in an else-branch where the variable was conditionally set in the if-branch.

### Cause

`set -u` (subset of `set -uo pipefail`) treats `$VAR` as a fatal error when unset. Conditional assignment (`if cond; then VAR=x; fi`) leaves `$VAR` unset on the else path. Referencing it without a default crashes.

### Fix

Use `${VAR:-default}` syntax for any conditionally-set variable:

```bash
if [ -f config.toml ]; then
    BACKLOG_JSON="$(parse-config)"
fi
# ... later:
log_skip "no backlog: ${BACKLOG_JSON:-(unconfigured)}"   # safe
```

### Prevention

When writing `set -uo pipefail` scripts with conditional assignments, audit every variable reference for `${VAR:-...}` form.

---

## 8. Python heredoc inside bash inside markdown command file

### Symptom

Slash command produces `SyntaxError: unexpected character after line continuation character` in Python output.

### Cause

Bash heredoc `<<PY` (unquoted EOF) performs variable expansion AND backslash escape interpretation on the heredoc body. Python f-strings using `\"` to escape internal double-quotes get mangled — the backslash gets consumed by bash before Python sees it.

```bash
python3 - <<PY
print(f"value: {data.get(\"key\", \"default\")}")   # WRONG — bash strips \"
PY
```

### Fix

Quote the heredoc EOF marker:

```bash
python3 - <<'PY'
print(f"value: {data.get('key', 'default')}")
PY
```

Or, use single quotes inside the f-string:

```python
print(f'value: {data.get("key", "default")}')
```

### Prevention

When embedding Python in shell scripts, ALWAYS use `<<'PY'` (quoted EOF marker) unless you genuinely need shell expansion inside the heredoc.

---

## 9. Skill name collisions across plugins

### Symptom

`/reload-plugins` shows 27 skills loaded but the available-skills list has duplicate `tdd`, `onion-ddd-workflow` etc. entries (one bundled, one loose). User sees the same skill name twice with slightly different descriptions; agent picks unpredictably.

### Cause

Two skills with the same `name:` exist:
- A loose skill at `~/.claude/skills/<name>/SKILL.md`
- A plugin-bundled skill at `<plugin>/skills/<name>/SKILL.md`

Claude Code namespaces the plugin one as `<plugin>:<name>` but the loose one keeps the bare `<name>`. Both surface in the available list.

### Fix

Reversibly disable one side by renaming `SKILL.md` ↔ `SKILL.md.disabled`:

```bash
mv ~/.claude/skills/tdd/SKILL.md ~/.claude/skills/tdd/SKILL.md.disabled
# Restore:
mv ~/.claude/skills/tdd/SKILL.md.disabled ~/.claude/skills/tdd/SKILL.md
```

(The `kaizen` plugin's `/kaizen:disable-dupes` automates this — but the mechanism is universal.)

### Prevention

Document which loose skills your plugin bundles in `ATTRIBUTIONS.md`. Suggest disable-dupes as part of post-install steps.

---

## 10. `gh repo create --remote=origin --push` fails when origin exists

### Symptom

```
✓ Created repository <owner>/<name> on GitHub
X Unable to add remote "origin"
```

### Cause

Pre-existing `origin` remote in the local repo (e.g. from a prior failed attempt or rename). `gh repo create --remote=origin` doesn't force-replace; it errors.

### Fix

Drop the stale origin first:

```bash
git remote remove origin 2>/dev/null
gh repo create <owner>/<name> --public --source=. --remote=origin --push
```

### Prevention

In any "first publish" script: idempotently remove `origin` before `gh repo create --remote=origin`.

---

## 11. Plugin `permissions` block schema is sparsely documented

**Discovered:** v1.3.0, while pre-authorising kaizen-owned scripts to suppress permission prompts on routine gate runs.

**Reproduce:** add a top-level `permissions: {allow: [...]}` field to `plugin.json`. Claude Code accepts it, BUT:

1. Documentation about valid pattern syntax is thin. `Bash(<exact-cmd>)`, `Bash(<cmd>:*)`, `Read(<glob>)`, `Write(<glob>)` work — but the precise grammar (regex? glob? exact?) isn't authoritative.
2. `${CLAUDE_PLUGIN_ROOT}` substitution inside patterns is plausible but unverified — write the block as if it works, then watch which tool calls still prompt.
3. `deny` exists symmetrically with `allow` but firing order / precedence is undocumented.

**Defence:** write the `allow` list conservatively (specific scripts, not wildcards on the whole filesystem), test by running the plugin's own slash commands to see what does/doesn't prompt, and document your assumptions in CHANGELOG. The first plugin to encounter this gotcha is YOU.

## 12. Agent `isolation` is per-invocation, not per-definition

**Discovered:** v1.3.0, while shipping the 3 kaizen agents (reviewer, backlog-curator, debt-auditor) that should always run in worktree-isolated contexts.

**The trap:** intuition says agent definitions in `agents/<name>.md` declare their own isolation level via frontmatter:

```yaml
---
name: kaizen-reviewer
isolation: worktree   # ← this DOES NOT exist
---
```

**Reality:** Isolation is set by the **caller** passing `isolation: "worktree"` to the `Agent` tool. The agent definition can't enforce its own sandboxing.

**Defence:**
- Document the isolation contract in the agent's body (`## Invocation contract` section).
- For programmatic dispatch (hooks, slash commands), build a wrapper that always passes the right isolation. Don't trust ad-hoc Agent() calls to remember.
- Hard rule for read-only agents: `tools` allowlist excludes Edit/Write so even without isolation, the agent can't mutate.

## 13. Statusline scripts have a <50 ms render budget

**Discovered:** v1.3.0, while wiring `scripts/statusline.sh`.

**The trap:** Claude Code re-runs the configured `statusLine.command` for **every status refresh** (per prompt, per tool call, sometimes more). A 200 ms statusline = 200 ms of perceptible lag on every interaction.

**Forbidden in statusline scripts:**

- Network I/O (no `curl`, no `gh api`)
- LLM calls (no MCP server invocation, no `claude` CLI re-entry)
- Slow git commands (`git log`, `git status` walks the index; `git rev-parse --show-toplevel` is fine — it just reads `.git/`)
- Process spawning beyond bare minimum (every fork costs ms)

**Allowed:**

- File reads (small JSON / TOML / symlink stat)
- `git rev-parse --show-toplevel` (~1 ms)
- `python3 -c '<short>'` for JSON parsing (~30 ms on cold start, less on warm)
- stdin parsing (Claude Code passes its event JSON on stdin — `cat` it once)

**Defence:** time your script with `time bash scripts/statusline.sh < /dev/null` — should be <100 ms cold, <30 ms warm. If slower, profile and inline.

## Pre-publish lint checklist

Compact, runnable pre-publish check covering all gotchas above:

```bash
# 1. hooks.json wrapper
python3 -c "
import json, glob, sys
for f in glob.glob('plugins/*/hooks/hooks.json'):
    d = json.load(open(f))
    if 'hooks' not in d:
        sys.exit(f'BUG #1: {f} missing top-level hooks wrapper')
"

# 2. one bash block per command
for f in plugins/*/commands/*.md; do
    n=$(grep -cE '!`(bash|python|node)' "$f")
    [ "$n" -gt 1 ] && { echo "BUG #2: $f has $n bash blocks"; exit 1; }
done

# 4. name: doctor / help / clear collisions
RESERVED='doctor help clear compact model config skills plugin reload-plugins'
for f in plugins/*/commands/*.md; do
    name=$(grep -E "^name:" "$f" | head -1 | sed 's/name: //')
    for r in $RESERVED; do
        [ "$name" = "$r" ] && { echo "BUG #4: $f shadows /$r"; exit 1; }
    done
done

# 6. cross-platform: no GNU-only utilities (in scripts only, not docs)
if grep -rEn 'readlink -f|find .* -printf' plugins/*/skills/*/scripts/ plugins/*/hooks/ 2>/dev/null \\
   | grep -v 'replaces GNU\\|portable real-path' \\
   | grep -q .; then
    echo "BUG #6: GNU-only utilities found in scripts"; exit 1
fi

echo "All gotcha-lint checks passed."
```

## Triggers for activating this skill

Phrases / symptoms that should pattern-match to load this skill:

- "Hook load failed"
- "expected record, received undefined"
- "1 error during load"
- "/plugin update" returns "(no content)" / "nothing to update"
- "Repository not found" from `git push` after `gh repo create` succeeded
- "ssh_askpass: exec ... No such file"
- "Host key verification failed"
- `readlink -f` / `find -printf` errors on macOS
- "unbound variable" in scripts with `set -u`
- "SyntaxError" inside python heredoc
- Slash command "ran the wrong thing"
- Plugin command name conflicts with built-in
- Skill duplicate / namespace noise

## Meta: why this skill exists

The kaizen plugin hit all 10 of these during its v1.0–v1.1.2 release cycle. Each was a multi-message debug session. Codifying them as a skill so future plugin work doesn't re-discover the same failures.

If you hit a new gotcha not covered here, please add a section + update the trigger phrases list — open an issue at github.com/YugeIceCone/kaizen-md.
