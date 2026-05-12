---
name: agent-formatting
description: Output-formatting discipline for assistant messages — slash commands stay plain, bash uses `!` for inline or a fenced ```bash block for terminal, never mixed. Triggers on "format my message", "show commands", "before drafting", "is this slash or bash", "how should I show this command", and whenever a response contains both a slash command and a shell command. Iron Law: never wrap a `/foo` slash command in a bash code fence or chain it with `&&`.
---

# Agent-formatting — slash vs bash discipline

How to present commands in assistant messages so the user can copy-paste them into the right surface. Mixing them is the single most common formatting bug for AI agents working in Claude Code.

## When to apply

Apply BEFORE drafting any assistant message that contains a command. ALWAYS apply when the response contains:

- Two or more commands (high risk of accidentally chaining incompatible kinds)
- A slash command (`/foo`, `/kaizen:bar`, `/workflow ...`)
- A bash command with a flag or path the user must adjust
- A pipeline (`|`, `&&`, `||`)

## The rules (machine-parseable schema)

The block below conforms to `assets/schemas/agent-formatting.schema.json` (mirrored by the `AgentFormattingSchema` dataclass in `skills/workflow/scripts/schemas.py`). External tools (ajv, jsonschema, future kaizen linters) can validate this block against the JSON Schema directly.

```yaml
# kaizen.agent-formatting.v1 — structured rules
# $schema: ../../assets/schemas/agent-formatting.schema.json
schema_version: 1
rules:
  - id: slash-plain
    applies_to: claude-code-slash-commands
    pattern: '^/[a-z][a-z0-9:_-]*'
    format:
      fence: none                  # NEVER inside ```bash
      one_per_line: true
      chain_with: none             # NEVER `&&` / `||` / `|`
    rationale: |
      Slash commands are intercepted and parsed by Claude Code itself,
      not by a shell. Chaining them with `&&` fails silently — only the
      first command runs; the rest become arguments.

  - id: bash-inline
    applies_to: bash-the-user-runs-in-this-session
    pattern: '^![^\n]+'
    format:
      prefix: "!"
      fence: none
      one_per_line: true
    rationale: |
      `!cmd` is Claude Code's inline-bash syntax — the command runs in
      the current session and the output lands directly in the
      conversation. Use this when you want the user to execute a short
      command and have you see the result.

  - id: bash-terminal
    applies_to: bash-the-user-runs-in-their-own-terminal
    format:
      fence: bash
      chain_with: shell-operators-allowed   # `&&`, `|`, etc. OK here
    rationale: |
      Use a ```bash code fence for multi-line shell snippets the user
      will run themselves (and whose output won't come back to you).
      Shell operators are fine inside the fence.

forbidden_constructs:
  - description: slash command inside a bash code fence
    example: |
      ```bash
      /kaizen:refresh-cache
      ```
    fix: |
      /kaizen:refresh-cache    # plain line, no fence

  - description: slash commands chained with &&
    example: "/kaizen:refresh-cache && /reload-plugins"
    fix: |
      /kaizen:refresh-cache
      /reload-plugins

  - description: bash + slash command in same fenced block
    example: |
      ```bash
      cd ~/.claude && /workflow audit
      ```
    fix: |
      ```bash
      cd ~/.claude
      ```
      Then:
      /workflow audit
```

## Concrete examples

### ❌ Wrong (what I kept doing before being corrected)

````
```bash
/kaizen:refresh-cache && /reload-plugins
```
````

The user gets a `bash` block that looks chained. They type the chain into a terminal — nothing happens (Claude Code isn't watching). Or they paste into Claude Code's prompt — only the first command runs, `&&` becomes an argument.

### ✅ Right

```
/kaizen:refresh-cache
/reload-plugins
```

Two plain lines, no fence. User types each one in Claude Code in turn. Both execute as intended.

### ✅ Right — inline bash you want to see output of

To check the current `~/.claude` git state, run:

```
!cd ~/.claude && git status
```

(The `!` prefix runs the command in this session; output lands here.)

### ✅ Right — terminal bash for the user's own shell

To set up the env for fresh installs:

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN="$(gh auth token)"
cd ~/.claude/local-marketplaces/kaizen-md
git pull
```

(Three lines, all genuine bash, `&&` would be fine, fenced as `bash` because the user runs them in their own terminal.)

## Decision flowchart

```
Want the user to run something?
├── Is it a Claude Code command (`/foo`)?
│   └── → plain line, no fence, one per line, no chaining
├── Do you want the OUTPUT in this conversation?
│   └── → `!cmd` on its own line (inline bash, one per turn ideally)
└── User runs it in their own terminal?
    └── → ```bash ... ``` fence, shell operators OK
```

## Iron Laws

1. **Never wrap a slash command in a `bash` code fence.** It is not bash; it is Claude Code syntax.
2. **Never chain slash commands with `&&`, `||`, `;`, or `|`.** Each must be on its own line.
3. **Never mix `!` inline-bash and a fenced bash block in the same step.** Pick one — they're for different contexts.
4. **When showing both a slash command AND a bash command in sequence**, format each in its own correct way and separate them with prose (not with `&&`).

## When to invoke this skill

- When drafting a message that contains a command.
- When the user says "format this command for me" / "is this slash or bash?" / "how do I show this in Claude Code?"
- When the user corrects formatting (a sign the agent's defaults drifted).
- Periodically when working on Claude-Code-meta projects (kaizen, plugins, hooks, commands).

## Related skills

- `kaizen:vibe-check` — pre-commit AI-coding discipline (this is its messaging-side analog)
- `kaizen:self-rag` — retrieval discipline (also a metacognitive checklist)
- `kaizen:writing-skills` — how to author other discipline skills (this one's exemplar)

## Why this exists

User explicitly corrected on 2026-05-12: "improve your assis messages separate slash commands from bash !". The corrected rule is now codified here so it survives session boundaries and applies across projects.
