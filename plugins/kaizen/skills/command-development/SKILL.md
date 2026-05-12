---
name: command-development
description: This skill should be used when the user asks to "create a slash command", "add a command", "write a custom command", "define command arguments", "use command frontmatter", "organize commands", "create command with file references", "use AskUserQuestion in command", or needs guidance on slash command structure, YAML frontmatter fields, dynamic arguments, bash execution in commands, or command development best practices for Claude Code. Adapted from claude-plugins-official/plugin-dev/command-development — sanitized for safe loading and trimmed for progressive disclosure.
version: 1.0.0
---

# Command Development for Claude Code

> Note: The `.claude/commands/` directory is the legacy format. New projects can also use `.claude/skills/<name>/SKILL.md`. Both load identically; the only difference is file layout. See the `skill-development` skill for the preferred format.

## Critical concept

**Commands are instructions FOR Claude, not messages to the user.**

When a user invokes `/command-name`, the command content becomes Claude's instructions. Write commands as directives TO Claude about what to do, not as descriptions OF what the command does.

Correct (instructions for Claude):

```text
Review the code for security vulnerabilities including SQL injection,
XSS, authentication issues. Provide line numbers and severity ratings.
```

Wrong (messages to user):

```text
This command will review your code for security issues.
You'll receive a report with vulnerability details.
```

The first tells Claude what to do; the second describes the command from the outside. Always use the first form.

## Command locations

| Location | Scope | Label |
|---|---|---|
| `.claude/commands/` | This project only | `(project)` |
| `~/.claude/commands/` | All projects (your machine) | `(user)` |
| `<plugin>/commands/` | When plugin enabled | `(plugin-name)` |

## File format

Commands are plain Markdown files. The file's path under `commands/` determines the slash name (`commands/review.md` → `/review`). Subdirectories namespace the command (`commands/git/commit.md` → `/commit (project:git)`).

Optional YAML frontmatter configures the command:

```yaml
---
description: Review code for security issues
allowed-tools: Read, Grep, Bash(git:*)
model: sonnet
argument-hint: [file-path]
disable-model-invocation: false
---

Review @$​1 for security vulnerabilities...
```

## Frontmatter fields

- **`description`** — one-line summary shown in `/help`. Default: first line of body. Keep under 60 chars.
- **`allowed-tools`** — comma-separated tool allowlist. Patterns: `Read, Write, Edit`, `Bash(git:*)`, `*`. Default: inherit from conversation.
- **`model`** — `haiku` / `sonnet` / `opus`. Use `haiku` for fast checks, `opus` for complex analysis. Default: inherit.
- **`argument-hint`** — autocomplete hint, e.g. `[pr-number] [priority]`. Helps user discoverability.
- **`disable-model-invocation`** — `true` to prevent the SlashCommand tool from auto-invoking. Use when the command should only run on manual invocation.

For exhaustive field semantics see `references/frontmatter.md`.

## Dynamic arguments

**`$​ARGUMENTS`** — captures everything after the slash command as one string.

```text
---
argument-hint: [issue-number]
---

Fix issue #$​ARGUMENTS following our coding standards.
```

Invocation: `/fix-issue 123` → "Fix issue #123 following…"

**Positional `$​1` `$​2` `$​3` …** — splits args on whitespace.

```text
---
argument-hint: [pr-number] [priority] [assignee]
---

Review PR #$​1 with priority $​2. Assign to $​3 for follow-up.
```

Invocation: `/review-pr 456 high alice` → "Review PR #456 with priority high. Assign to alice…"

Note: only the bare-`$` form (`$​ARGUMENTS`, `$​1`) is substituted. `$​{ARGUMENTS}` is NOT — a common gotcha.

## File references with `@`

Inject file contents into the command:

```text
---
argument-hint: [file-path]
---

Review @$​1 for code quality and best practices.
```

`/review-file src/api/users.ts` → Claude reads `src/api/users.ts` before processing.

Multiple files work: `Compare @src/old.js with @src/new.js`. Static paths work without args: `Review @package.json and @tsconfig.json`.

## Bash execution with `!​`

Inline bash output capture happens BEFORE Claude sees the prompt. The result substitutes into the prompt body.

**Escape convention for this skill:** examples below use zero-width spaces (U+200B) to neutralize Claude Code's substitution machinery when this skill is rendered:

- `!​\`...\`` — ZWSP between `!​` and the backtick stops the loader from executing the bash
- `$​ARGUMENTS`, `$​1`, `$​{CLAUDE_PLUGIN_ROOT}` — ZWSP after `$` stops the slash-command processor from substituting the variable

When copy-pasting these examples into your own commands, strip the invisible ZWSP characters. The visible syntax is what to write.

```text
---
description: Review code changes
allowed-tools: Read, Bash(git:*)
---

Files changed: !​`git diff --name-only`

Review each file for code quality, bugs, and test coverage.
```

`Bash(git:*)` restricts execution to `git ...` subcommands — keep `allowed-tools` narrow.

## `$​{CLAUDE_PLUGIN_ROOT}` for plugin commands

Plugin commands receive `$​{CLAUDE_PLUGIN_ROOT}` — absolute path to the plugin dir. Use it for portable references to plugin-bundled scripts, configs, templates:

```text
---
allowed-tools: Bash(node:*)
---

Analysis: !​`node $​{CLAUDE_PLUGIN_ROOT}/scripts/analyze.js $​1`
```

Without `$​{CLAUDE_PLUGIN_ROOT}`, the command breaks on every other user's machine. Always use it.

## Patterns

### Review pattern

```text
---
description: Review the current diff
allowed-tools: Read, Bash(git:*)
---

Files changed: !​`git diff --name-only`

Review each file for:
1. Code quality and style
2. Potential bugs or issues
3. Test coverage
4. Documentation needs
```

### Multi-step workflow

```text
---
description: Complete PR workflow
argument-hint: [pr-number]
allowed-tools: Bash(gh:*), Read
---

PR #$​1 details: !​`gh pr view $​1`

1. Review changes
2. Run checks
3. Approve or request changes
```

### Configuration-driven

```text
---
description: Deploy via plugin config
argument-hint: [environment]
allowed-tools: Read, Bash(*)
---

Config: @$​{CLAUDE_PLUGIN_ROOT}/config/$​1-deploy.json

Deploy to $​1 using config settings; monitor and report status.
```

## Validation patterns

Validate args + resources before processing:

```text
---
argument-hint: [environment]
---

Env check: !​`echo "$​1" | grep -E "^(dev|staging|prod)$" || echo "INVALID"`

If $​1 is invalid, list the valid environments and show usage.
Otherwise, deploy to $​1.
```

```text
---
argument-hint: [config-file]
---

File check: !​`test -f $​1 && echo "EXISTS" || echo "MISSING"`

If MISSING, explain expected location + format.
If EXISTS, process: @$​1
```

## Best practices

- **Single responsibility.** One command, one task. Compose via multi-step prompts, not god-commands.
- **Verb-noun naming.** `review-pr`, `fix-issue`, `deploy-staging`. Avoid `test` / `run` (too generic).
- **Narrow `allowed-tools`.** Prefer `Bash(git:*)` over `Bash(*)`.
- **Document arguments.** Always set `argument-hint`. Validate inputs in the prompt.
- **Use `$​{CLAUDE_PLUGIN_ROOT}`** for any plugin file reference. No hardcoded absolute paths.
- **Test bash blocks first.** Run the command in a terminal before embedding.
- **Keep commands fast.** Long-running bash in `!​` blocks delays every invocation.

## Common mistakes

| Mistake | Fix |
|---|---|
| Writing for the user ("This command does X") | Write for Claude ("Review X for Y") |
| `Bash(*)` everywhere | Scope to the specific binary subset |
| `$​{ARGUMENTS}` (curly braces) | Use bare `$​ARGUMENTS` |
| Hardcoded paths in plugin commands | `$​{CLAUDE_PLUGIN_ROOT}/...` |
| Missing `argument-hint` | Always document arg format |
| Long bash in `!​` block | Move to a script; reference via `!​\`bash $​{CLAUDE_PLUGIN_ROOT}/scripts/x.sh\`` |

## Troubleshooting

**Command not appearing in `/help`** — wrong directory, missing `.md` extension, or session needs reload. Restart CC.

**Args not substituting** — using `$​{ARG}` instead of bare `$​ARG`. Check `argument-hint` matches actual invocation. No extra spaces.

**Bash failing** — `allowed-tools` missing `Bash` or scoped too narrowly. Test the bash in a terminal. Check for restricted-mode flags.

**`@` file references not working** — wrong path (use project-relative or absolute). `Read` tool not in `allowed-tools`. File doesn't exist (handle gracefully in prompt).

## Additional resources

For deeper detail consult:

- `references/frontmatter.md` — every field with edge cases
- `references/patterns.md` — review / testing / docs / workflow / configuration patterns
- `references/plugin-features.md` — `$​{CLAUDE_PLUGIN_ROOT}` semantics + multi-component plugin patterns

Also see the kaizen plugin's own `commands/` dir for ~30 working examples of each pattern in production.
