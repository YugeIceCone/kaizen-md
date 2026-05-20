# kaizen plugin — DevOps cheat-sheet

**Single-page reference for plugin maintainers.** Where to extend, what to edit, current limitations, gotchas.

Last refreshed: 2026-05-17.

---

## File layout (the 2-minute orientation)

```
plugins/kaizen/
├── .claude-plugin/
│   └── plugin.json              ← manifest: version, permissions, keywords
├── .mcp.json                    ← MCP gateway entry (1 server: "kaizen")
├── hooks/
│   ├── hooks.json               ← event → script registrations
│   └── claude/
│       ├── _bash_gate.py        ← PreToolUse(Bash) decision module
│       ├── _bash_discipline_scan.py ← shared scan() — soft advisories
│       └── *.sh                 ← 18 registered event hooks
├── commands/                    ← 48 slash commands (/kaizen:<name>)
├── bin/                         ← 50 CLI wrappers (kaizen-*) + 1 dispatcher (kaizen)
├── agents/                      ← 6 sub-agent personas
├── assets/schemas/              ← 13 plugin-wide JSON schemas
├── skills/
│   ├── workflow/                ← THE big skill — discipline + orchestration
│   │   ├── domain/              ← yaml SSOTs (routines, git-discipline, schemas)
│   │   ├── application/         ← loaders + codegen
│   │   └── scripts/             ← ~70 Python + ~25 shell scripts (CLIs + MCP)
│   ├── iron-laws/               ← the 21 iron laws + checker
│   ├── efficient-tool-use/      ← shell anti-pattern catalog + scanner
│   ├── verify-before-execution/ ← RED-GREEN gate skill
│   ├── audit/, review/, refactor/, brain/, …  ← 80+ other skills
│   └── …
├── tests/                       ← unittest suite
├── ATTRIBUTIONS.md              ← upstream-author credits
├── CHANGELOG.md                 ← versioned change log
├── CONTRIBUTING.md              ← maintainer how-to
└── DEVOPS-CHEAT-SHEET.md        ← (this file)
```

## Extension points (what goes where)

| You want to add… | Put it in | Wire it via |
|---|---|---|
| A new **slash command** (`/kaizen:foo`) | `commands/foo.md` (YAML frontmatter `name` + `description` + optional `argument-hint`; body with `!`-prefix bash or fenced bash block) | Auto-discovered by Claude Code. Optional: `bin/kaizen-foo` wrapper so it's also callable from bash. |
| A new **CLI tool** (Python) | `skills/workflow/scripts/foo.py` + `bin/kaizen-foo` wrapper | Iron-law `bin-wrapper-per-cli` requires the wrapper. Add explicit permission entry in `.claude-plugin/plugin.json` (the `*.py` wildcard is for runtime but the iron-law looks for filename). |
| A new **MCP tool** | `skills/workflow/scripts/foo_mcp.py` (FastMCP server with `@mcp.tool()` decorators) | Add `("foo", "foo_mcp")` to `gateway.py::SUBSERVERS`. Optionally add tool names to `CURATED_CORE` so they're always-visible (default ~15 tool budget). |
| A new **hook script** | `hooks/claude/<event>-<purpose>.sh` (e.g. `posttooluse-foo.sh`) | Register in `hooks/hooks.json` under the right event. Use `bash` + source `_paths.sh` for plugin-root resolution. Always include a `KAIZEN_<NAME>_DISABLE=1` bypass knob (hook-bypass-knob iron-law). |
| A new **skill** | `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`, `metadata.version`) | Auto-discovered. Body MUST be read in full by callers (write the trigger phrases in `description` clearly). |
| A new **iron law** | `skills/iron-laws/domain/iron-laws.yaml` (yaml entry) + `skills/workflow/scripts/_iron_laws.py::check_<name>()` if `enforcement: auto` | Regenerate the reference: `python3 skills/iron-laws/application/codegen.py`. Tests in `tests/test_iron_laws.py`. |
| A new **anti-pattern (efficient-tool-use)** | `skills/efficient-tool-use/domain/anti-patterns.yaml` (yaml entry with `id`, `tool`, `bad_pattern`, `why_bad`, `replacement`, `severity`, optional `detect` regex) | The pre-commit etu gate auto-picks it up. Add a `# noqa: etu` test case if false-positive prone. |
| A new **workflow routine** | `skills/workflow/domain/routines.yaml` (`routines:` array) + each new stage to `stage_skill_map` | `python3 skills/workflow/application/codegen.py` regenerates `references/routines.md`. Tests in `skills/workflow/application/_tests.py`. |
| A new **assets/schema** | `assets/schemas/<name>.schema.json` | Add a consumer (validator script). Orphan schemas trip `kaizen-surface validate`. |

## Editing existing things (what to touch where)

### "I want to change…"

| Task | Edit | Side-effects |
|---|---|---|
| Plugin version | `.claude-plugin/plugin.json::version` + `CHANGELOG.md` `[Unreleased]` → tagged section | `kaizen version` reflects it |
| Add to global PATH | Already there via `kaizen-env.sh` ; runs from `~/.bashrc` after `/kaizen:env install` | Subshells under the user's terminal pick it up; agent Bash tool inherits from user shell |
| Add an MCP tool to "always visible" | `scripts/mcp/gateway.py::CURATED_CORE` list | Default tool budget ~15; consider what to drop |
| Make a hook non-blocking | Return `{}` from the hook (or `systemMessage` not `permissionDecision: ask`) | PreToolUse `ask` blocks until user confirms; SystemMessage just surfaces a warning |
| Bypass a check temporarily | Set the documented `KAIZEN_<X>_DISABLE=1` env var per command | See `kaizen iron-laws show hook-bypass-knob` |
| Add a new gate to pre-commit | Edit `scripts/git-hooks/pre-commit.sh` (Check N+1) OR add to gatekeeper sub-gates (Python) | Iron-laws checker is Check 7.5; gatekeeper pre-flight is Check 7.6 — model new ones after these |
| Change which etu severity blocks | `skills/efficient-tool-use/domain/anti-patterns.yaml::severity` (error / warn / info) | error → PreToolUse `ask`; warn/info → systemMessage |
| Add a tool to the canonical envelope | Import `_envelope.emitter(tool="kaizen-X")`, swap `print(json.dumps(...))` → `_emit(...)`. Append to `_RETROFIT_TOOLS` in `tests/test_envelope.py`. | See `skills/efficient-tool-use/references/envelope-retrofit.md` for the full inventory + pattern |
| Add a routine stage | `skills/workflow/domain/routines.yaml::stage_skill_map` + routine's `stages:` list | Codegen + drift-check via `codegen.py --check` |

## Current limitations (what bites and how to work around)

| Limitation | Workaround / mitigation |
|---|---|
| **`bin-wrapper-per-cli` iron-law uses strict filename match.** A wrapper `bin/kaizen-foo` doesn't satisfy a script `foo_bar.py`; you need `bin/kaizen-foo-bar` even when semantic match is fine. | Create an alias bin wrapper (`cp` an existing one + `sed` to point at the new script). |
| **`plugin-manifest-permissions` iron-law doesn't recognize wildcards.** The `*.py` wildcard in plugin.json covers runtime invocation, but the iron-law looks for literal filenames. | Add an explicit entry per new script. Or improve the iron-law (open). |
| **`_envelope.py` is workflow-skill-local.** Other skills (karpathy, etc.) need cross-skill sys.path insert. | Use `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workflow" / "scripts"))` before `import _envelope`. |
| **Hooks run in non-interactive subshells.** `~/.bashrc` may or may not source — depends on shell + invocation. | Always derive `PLUGIN_ROOT` via `source _paths.sh` (symlink-safe). Don't rely on env vars from the user's interactive shell. |
| **MCP tools don't yet use canonical envelope.** MCP protocol has its own response wrapper. | Future work — see `envelope-retrofit.md::MCP` section. For now, MCP tools return raw dicts; agents parse per-tool. |
| **17 CLI tools lack `--json` flag.** `backlog`, `brain`, `cache`, `context`, `daemon`, `knowledge_index`, … — these need flag wiring before envelope retrofit. | See `envelope-retrofit.md::needs-json-flag` for the list. Mechanical work — argparse `--json` + envelope emit. |
| **`pre-commit.sh` is bash; gatekeeper is Python.** Two checker surfaces overlap. | Use bash gate for compile/secret/backlog checks (fast, no Python startup). Use `kaizen-gatekeeper` for iron-laws + etu + karpathy + validator aggregation. Both live; pre-commit Check 7.5/7.6 wires them. |
| **`kaizen-surface validate` reports drift but can't auto-fix.** `install` / `diff` subcommands are placeholders. | Manual edit of `hooks.json` / `gateway.py::SUBSERVERS` / `plugin.json` for now. |
| **Karpathy scripts share the underscore-prefix exemption hack.** `_kaizen_dispatcher.py` (the CLI dispatcher) is named with `_` to skip `bin-wrapper-per-cli` because its wrapper is `bin/kaizen`, not `bin/kaizen-_kaizen-dispatcher`. | Convention: dispatchers / helper modules called by bin/ wrappers use `_` prefix to opt out of the iron-law. |
| **`.kaizen/` runtime artifacts** (state.json, deletions.jsonl, snapshot.md) are gitignored via re-ignore rules in `.kaizen/.gitignore` after the broad `!workflow/**` whitelist. | If you add a new ephemeral file under `workflow/`, add it to the re-ignore block in both `.kaizen/.gitignore` AND the heredoc in `setup.sh`. |
| **Pre-commit gate's CHANGELOG dance.** Multi-commit work often touches CHANGELOG. The gate's secret-pattern scan can false-positive on prose. | The session-pattern is `git stash push plugins/kaizen/CHANGELOG.md` → make commit → `git stash pop` → resolve conflict → repeat. Annoying but reliable. |
| **`kaizen --time <sub>` doesn't work for built-in subcommands** (`version`, `list`, `commands`, `help`). | Built-ins short-circuit BEFORE the timing block. Use external wrappers like `time kaizen <sub>` for those. Or extend `_kaizen_dispatcher.py::main` to wrap built-ins too. |

## Common gotchas (the "wait, why didn't that work?" list)

1. **You added a `# noqa: etu` comment but the scanner still flags the line.** The comment must be on the same line OR within 5 lines above the flagged line (no other code in between). See `etu_scan.py::_suppressed`.

2. **A new CLI script's `--help` works but `kaizen-foo --help` says "unknown subcommand".** The dispatcher resolves via filename match: `kaizen-foo` → `bin/kaizen-foo` must exist as an executable. Symlinks work too.

3. **Two scripts both `import _loader` and one of them got the wrong loader.** Module-name collision. Use `importlib.util.spec_from_file_location` with unique synthetic names (`kaizen_iron_laws_loader`, etc.) instead of relying on `sys.path` order. See `_kaizen_dispatcher.py::_load_module` for the pattern.

4. **A new sub-server in `gateway.py::SUBSERVERS` doesn't appear in agent tool lists.** The gateway needs `/reload-plugins` (or restart the Claude Code session) to re-spawn. Also check the `RegexSearchTransform` — tools NOT in `CURATED_CORE` are reached via `kaizen_search_tools` + `kaizen_call_tool`, not the default list.

5. **`kaizen-surface validate` flags `mcp-no-tools` on your new `_mcp.py`.** You forgot `@mcp.tool()` decorators OR the FastMCP `mcp = FastMCP(...)` is named differently. The scanner looks for `@<X>.tool(` regex.

6. **Hooks fire but their output isn't visible.** Hooks emit JSON; Claude Code consumes only `hookSpecificOutput.additionalContext` / `systemMessage` / `permissionDecision`. Other top-level keys are ignored. Don't `print()` plain text — it goes to a void.

7. **A new envelope retrofit's test fixture fails CI.** The retrofit needs an entry in `tests/test_envelope.py::_RETROFIT_TOOLS`. Without it, `TestRetrofittedToolsValidate` doesn't exercise the new tool — but `kaizen-gatekeeper check --all` running in CI will surface the violation later.

8. **`git commit` fails with "vendored skill modified".** The `no-modify-vendored` iron-law's detect list is now EMPTY (retired 2026-05-17). If this fires, check `skills/iron-laws/domain/iron-laws.yaml::no-modify-vendored` — someone may have re-added entries.

9. **You changed `routines.yaml` and `codegen.py --check` fails.** Re-run `python3 skills/workflow/application/codegen.py` to regenerate `references/routines.md`. The check guards against drift between yaml + rendered markdown.

10. **A subprocess call works locally but fails in tests.** Tests run from `_REPO_ROOT` (set via `Path(__file__).resolve().parents[3]`). Use `cwd=_REPO_ROOT` in `subprocess.run` calls. See `tests/test_envelope.py` for the pattern.

## Testing — quick reference

| Run | Command |
|---|---|
| Full test suite | `python3 -m unittest discover plugins/kaizen/tests` |
| One test module | `python3 -m unittest plugins.kaizen.tests.test_envelope` |
| With verbosity | `python3 -m unittest -v plugins.kaizen.tests.test_envelope` |
| Iron-laws check (staged) | `kaizen iron-laws check --staged --json` |
| Surface validate | `kaizen-surface validate` |
| Gatekeeper aggregate | `kaizen-gatekeeper check --all` |
| Plugin-development validator | `python3 plugins/kaizen/skills/plugin-development/scripts/validate.py` |
| Codegen drift (iron-laws) | `python3 plugins/kaizen/skills/iron-laws/application/codegen.py --check` |
| Codegen drift (workflow) | `python3 plugins/kaizen/skills/workflow/application/codegen.py --check` |
| Hot-path hook performance | `kaizen metrics top --kind hook` |
| etu scanner self-test | `python3 plugins/kaizen/skills/efficient-tool-use/application/etu_scan.py --all` |

## Releases

Tag with `v<X.Y.Z>` after a CHANGELOG cut. The `[Unreleased]` section becomes the new tag's body.

```bash
# Edit CHANGELOG.md: change "## [Unreleased]" to "## [X.Y.Z] — YYYY-MM-DD"
# Add new "## [Unreleased]" empty section above
# Bump version in .claude-plugin/plugin.json
git add CHANGELOG.md .claude-plugin/plugin.json
git commit -m "release: vX.Y.Z"
git tag vX.Y.Z
git push origin master --tags    # only with explicit user authorization
```

There's no automated release script. `kaizen publish release vX.Y.Z` is for the marketplace-publish flow specifically (separate from version tag).

## Where to look for X

| X | File |
|---|---|
| All slash commands | `commands/*.md` (`kaizen commands list` to enumerate) |
| All CLI tools | `bin/kaizen-*` (`kaizen list` to enumerate by category) |
| All MCP tools | `skills/workflow/scripts/*_mcp.py` (`kaizen-surface list --kind mcp` to enumerate) |
| All hooks | `hooks/hooks.json` (`kaizen-surface list --kind hooks` to enumerate) |
| All iron laws | `skills/iron-laws/domain/iron-laws.yaml` (`kaizen iron-laws list --json` to enumerate) |
| All workflow routines | `skills/workflow/domain/routines.yaml` (`kaizen workflow list` to enumerate) |
| All etu anti-patterns | `skills/efficient-tool-use/domain/anti-patterns.yaml` |
| Envelope schema | `assets/schemas/tool-output.schema.json` |
| Envelope retrofit status | `skills/efficient-tool-use/references/envelope-retrofit.md` |
| Plugin attribution | `ATTRIBUTIONS.md` |
| Plugin version | `.claude-plugin/plugin.json::version` |
| Recent change log | `CHANGELOG.md` (`[Unreleased]` is the staging section) |

## When in doubt

1. **`kaizen list`** — every CLI subcommand
2. **`kaizen commands`** — every slash command (`/kaizen:<name>`)
3. **`kaizen-surface validate`** — registration drift in seconds
4. **`kaizen-gatekeeper check --all`** — every Python check in one verdict
5. **`kaizen iron-laws check --all`** — just the iron laws

If none of those answer the question, it's not in the plugin yet. File a backlog item via `kaizen backlog add` and pair with a `BK-N` reference in the commit that adds it.

## Where this cheat-sheet itself lives

`plugins/kaizen/DEVOPS-CHEAT-SHEET.md` at the plugin root (sibling to `CHANGELOG.md`, `CONTRIBUTING.md`, `ATTRIBUTIONS.md`). Updates land alongside CHANGELOG entries when extension points change.
