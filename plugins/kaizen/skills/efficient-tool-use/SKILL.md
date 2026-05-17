---
name: efficient-tool-use
description: Tool-selection + anti-patterns for the shell toolbox (grep / rg / sed / awk / find / xargs / jq). Triggers on "is there a faster way", "this grep is slow", "should I use sed or python", "find vs rg", "before I write a bash loop", "best way to scan this codebase". Iron-Law skill — read in full before chaining 3+ shell commands.
metadata:
  version: 1.0.0
---

# Efficient Tool Use

The right tool used wrong is slower than the wrong tool used right. The wrong tool used right is slower than the right tool. Match tool to job, then use it correctly.

## ⚠ Iron Law — read in full

Skip nothing. The tool-selection matrix means nothing without the per-tool best-practice + anti-pattern sections. Skimming to "grep best practices" without reading the selection matrix produces over-optimized bad-choice pipelines.

## Tool-selection matrix (decide first, type second)

| Task | First-choice tool | Fallback | Why |
|---|---|---|---|
| Find file by name | `find . -name '*.rs'` or `fd` | — | scope to `.`, never `/` |
| Find files containing text | `rg "pattern"` | `grep -rn "pattern"` | rg is 5-10× faster, honors `.gitignore` |
| List files containing text | `rg -l "pattern"` | `grep -rl "pattern"` | `-l` skips per-line work entirely |
| Count matches | `rg -c "pattern"` | `grep -c "pattern"` | never `grep ... \| wc -l` |
| Count matching files | `rg -l "pattern" \| wc -l` | — | `-c` is per-file count, `-l` is per-file existence |
| Replace text in-place across files | `sed -i 's/old/new/g' files…` | python `pathlib` for multi-line | one-shot only; multi-line → python |
| Structural code change (rename a fn, etc.) | `ast-grep` (see `kaizen:ast-grep-*`) | — | regex can't see syntax — no false positives on comments/strings |
| JSON manipulation | `jq` | python `json` | never `grep '"key":'` JSON |
| Tabular text (columns, sums) | `awk` one-liner | python for >5 lines | column 7 in 50 chars; don't pull in pandas |
| Parallel batch | `xargs -P $(nproc)` or `parallel` | python `concurrent.futures` | not bash `&` loops |
| Wait for condition (file appears, port opens) | `until <test>; do sleep 1; done` | — | never blind `sleep N` |
| File rename by pattern | `for f in *.old; do mv "$f" "${f%.old}.new"; done` | — | quote vars; parameter expansion |
| Glob across deep tree | `**/*.py` with `shopt -s globstar` or `find -name` | — | bare `*.py` only matches one level |

When in doubt: **`rg` for text, `fd` for filenames, `ast-grep` for syntax, `jq` for JSON, `python` for anything stateful.** Default to the modern Rust-based tools when available; they're faster + saner defaults.

## ripgrep (`rg`) — first-choice scanner

```bash
rg "pattern"                              # recursive from .
rg -l "pattern"                           # files-with-matches (fastest mode)
rg -c "pattern"                           # per-file count
rg -F "literal.string"                    # fixed-string mode (faster, no regex)
rg --type rust "pattern"                  # filter by language
rg -g '*.rs' -g '!target/' "pattern"      # glob include/exclude
rg -A 5 -B 2 "pattern"                    # 5 after, 2 before
rg --json "pattern"                       # for programmatic consumption
rg --files                                # list all files rg WOULD scan (gitignore-aware)
```

Key flags worth remembering: `-l` (files only — huge speedup), `-F` (fixed string — faster + safer), `--type X` (over `--include='*.X'`), `--json` (when piping to scripts).

## grep — when rg isn't installed

Same flag spelling for `-r`, `-n`, `-l`, `-c`, `-F`, `-i`, `-w`, `-A`, `-B`, `-C`. Extra:

- `-E` for ERE (no escaping `+ ? | ( )`)
- `-P` for PCRE (lookaround, named groups)
- `--include='*.rs' --exclude-dir=target` to scope
- `-z` for null-separated (when pairing with `find -print0`)

### grep anti-patterns (refuse these on review)

| Pattern | Why bad | Fix |
|---|---|---|
| `grep "X" \| grep -v "Y" \| grep "Z"` | 3 forks + 3 reads | `rg "X.*Z"` + final `\| rg -v "Y"` |
| `grep -rn "X" /` | scans entire filesystem | `grep -rn "X" .` or `rg "X"` |
| `grep "X" \| wc -l` | useless wc | `grep -c "X"` (per-file) or `rg -c "X" \| awk -F: '{s+=$2} END{print s}'` (total) |
| `find . -name "*.py" \| xargs grep "X"` | breaks on spaces | `rg "X" -g '*.py'` or `grep -rn --include='*.py' "X" .` |
| `grep "X" $(find ...)` | breaks on spaces, exceeds `ARG_MAX` | `find ... -exec grep "X" {} +` |
| `grep "X" file \|\| true` to suppress exit code | swallows real errors | `grep -q "X" file; result=$?` (explicit) |

## sed — when an in-place text edit is all you need

```bash
sed -i 's/old/new/g' file                 # GNU
sed -i '' 's/old/new/g' file              # BSD/macOS (note the '')
sed -E 's/(foo|bar)/X/g' file             # ERE (matches rg/grep -E)
sed '5,10d' file                          # delete lines 5-10
sed -n '/start/,/end/p' file              # print between two markers
sed -E -e 's/A/B/' -e 's/C/D/' file       # multiple expressions
```

### sed anti-patterns

| Pattern | Why bad | Fix |
|---|---|---|
| `sed -i 's/X/Y/g' file` without `git diff` after | silent corruption if regex wrong | always `git diff` after; or `sed -i.bak` then diff |
| `cat file \| sed ...` | useless `cat` | `sed ... file` |
| `sed` chains for multi-line / context-aware edits | sed sees one line at a time | python with `pathlib.read_text()` + multiline `re` |
| Portability assumption (`-i` works the same on Linux+macOS) | BSD needs `''`, GNU rejects it | use python if cross-platform; or `sed --version 2>/dev/null && sed -i 's/.../...//' \|\| sed -i '' 's/.../...//'` |
| Multi-pattern sed where escape-soup grows | unreadable, brittle | switch to python |

## find — when you need filesystem traversal

```bash
find . -name '*.rs' -type f                       # files matching glob
find . -name 'node_modules' -prune -o -name '*.js' -print  # skip a dir
find . -name '*.py' -exec ruff check {} +         # batched exec (+, not \;)
find . -mtime -7 -type f                          # changed in last 7 days
find . -size +10M                                 # files >10MB
find . -newer reference.txt                       # newer than ref
find . -name '*.tmp' -print0 \| xargs -0 rm       # safe with weird filenames
```

### find best practices

- **Always scope:** `find . ...`, never `find /` — exhausts resources on large trees
- **Predicate order matters:** put cheap filters first (`-name 'X' -type f`) — `-name` is cheaper than `-type`
- **Use `+` not `\;`:** `-exec foo {} +` batches → 1 fork. `-exec foo {} \;` → 1 fork per file
- **`-prune` early:** prune before `-name` to skip whole subtrees: `-name node_modules -prune -o -name '*.js' -print`
- **Pair `-print0` with `xargs -0`:** the only safe way to handle paths with spaces/newlines/quotes
- **Regex alternation order:** put the LONGEST alternative first — `-regex '.*\.\(tsx\|ts\)'` matches `.tsx`; `.*\.\(ts\|tsx\)` silently skips `.tsx` (regex stops at first match)

### find anti-patterns

| Pattern | Why bad | Fix |
|---|---|---|
| `find / -name X` | scans entire filesystem | `find . -name X` or specific subtree |
| `find ... -exec cmd {} \;` | N forks for N files | `-exec cmd {} +` (1 fork) |
| `for f in $(find ...); do ...; done` | breaks on spaces; subshell strip | `while IFS= read -r -d '' f; do ...; done < <(find ... -print0)` |
| `find ... -regex '.*\.\(ts\|tsx\)'` | shorter alt matches first → `.tsx` silently skipped | longest alternative first: `'.*\.\(tsx\|ts\)'` |

## bash — when you must script it

### Mandatory first lines for any non-trivial script

```bash
#!/usr/bin/env bash
set -euo pipefail
```

- `-e` exit on error (any unhandled non-zero)
- `-u` exit on unset variable (no `$typo` silently empty)
- `-o pipefail` exit if any pipeline stage fails (not just the last)
- Optional: `-x` for trace (debug only); `IFS=$'\n\t'` to disable word-splitting on space

### bash best practices

- **Always quote vars:** `"$var"` not `$var` — prevents word-splitting + glob expansion
- **`[[` over `[`:** bash-builtin, no fork, supports `=~`, `&&`, `\|\|` inside
- **`$(cmd)` over backticks:** nestable, readable, supported everywhere modern
- **`${var:-default}`:** fallback for unset/empty
- **`local` in functions:** prevents global pollution
- **`readonly` for constants:** prevents accidental mutation
- **`printf` over `echo`:** portable behavior; `echo` flags vary
- **`mktemp -d` + `trap`:** scoped temp dirs, automatic cleanup:
  ```bash
  tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' EXIT
  ```
- **`shellcheck` every script:** catches 80% of these issues automatically

### bash anti-patterns

| Pattern | Why bad | Fix |
|---|---|---|
| `[ $foo = "bar" ]` (unquoted) | breaks if `$foo` is empty or has spaces | `[[ "$foo" = "bar" ]]` |
| `cd $dir` (no error check) | `cd` failure continues silently | `cd "$dir" \|\| exit 1` (or use `set -e`) |
| `ls *.txt \| while read f; ...` | breaks on weird filenames, no globs match → `*.txt` literal | `for f in *.txt; do [ -e "$f" ] \|\| continue; ...; done` |
| `cmd1 && cmd2` for error handling | breaks under `set -e` (the `&&` masks the failure) | just `cmd1; cmd2` with `set -e` |
| Missing `set -o pipefail` | `false \| true` succeeds | `set -euo pipefail` always |
| `eval` on user input | code injection | refuse; restructure to not need eval |
| `rm -rf $foo/bar` with `$foo` possibly empty | `rm -rf /bar` on empty | `: "${foo:?foo is required}"` first |
| `sleep N` to wait for state | flaky + slow | `until <test>; do sleep 1; done` (timeout: `timeout 30 bash -c 'until ...'`) |
| Loop with one fork per iteration: `while read l; do x "$l"; done` | N forks | `xargs -I {} x {} < file` or batch: `xargs x < file` |
| `cmd 2>/dev/null \|\| true` to suppress | hides real errors | catch specific exit code: `cmd; rc=$?; case $rc in 0) ;; 1) ;; *) exit $rc;; esac` |

## xargs — bounded parallelism + safe path handling

```bash
find . -name '*.py' -print0 \| xargs -0 -P "$(nproc)" -I {} ruff check {}
```

- `-0` paired with `find -print0` — only safe form for arbitrary paths
- `-P N` — N parallel processes (use `$(nproc)` for CPU count)
- `-I {}` — substitute `{}` (otherwise args append to end)
- `-n N` — at most N args per invocation (batch sizing)
- `-r` (GNU) — no-op if input is empty (don't run cmd with zero args)

### xargs anti-patterns

| Pattern | Why bad | Fix |
|---|---|---|
| `find ... \| xargs cmd` (no `-0`) | breaks on spaces | `find ... -print0 \| xargs -0 cmd` |
| `xargs -P N` without bounded N | spawns 1000s of processes | `xargs -P "$(nproc)"` (or `-P 8`) |
| `xargs cmd {}` (no `-I`) | args appended to end, not substituted | `xargs -I {} cmd {} extra-arg` |

## awk — short-form column / aggregation tool

```bash
awk '{print $7}' file                              # column 7 (1-indexed)
awk -F: '{print $1}' /etc/passwd                   # custom delimiter
awk '$3 > 100 {print $1, $3}' file                 # filter + project
awk '{s+=$2} END {print s}' file                   # sum column 2
awk 'NR==1 {next} {print}' file                    # skip header
awk '/pattern/{c++} END{print c}' file             # count pattern matches
awk -F'\t' 'NR>1 && $5=="active"' table.tsv        # filter rows
```

When awk grows past 5 lines or needs dicts/sets → switch to python.

## jq — JSON manipulation

```bash
jq '.field' file.json                              # extract one field
jq '.items[] \| .name' file.json                   # iterate + project
jq -r '.items[].id' file.json                      # -r = raw (no quotes)
jq '.[] \| select(.active == true)' file.json      # filter
jq '[.[] \| {id, name}]' file.json                 # rebuild structure
jq -s 'add' a.json b.json                          # slurp + merge arrays
echo '{}' \| jq --arg name "$NAME" '.name=$name'   # inject shell var
```

### jq anti-patterns

| Pattern | Why bad | Fix |
|---|---|---|
| `grep '"key":' file.json` | misses nested keys; brittle | `jq '.key' file.json` |
| `jq` with bash-string interpolation of values | quoting hell, injection | `jq --arg X "$X" '.field = $X'` |
| Parsing jq output with `cut`/`awk` | jq can already shape it | add a jq filter; use `-r` for raw |

## When to abandon shell for python

The break-even point:

| Stay in shell | Move to python |
|---|---|
| <50 lines, single transformation | >50 lines |
| Pipeline of well-known tools | Multi-step state (dicts, sets) |
| File system glue (mv, ln, etc.) | Parsing structured data (JSON, YAML, CSV beyond 1 column) |
| One-off | Will be re-used or tested |
| Linear flow | Branching logic, error recovery |
| Single error mode | Multiple error classes to distinguish |

**Trigger to switch:** if you're writing nested `awk` inside `sed` inside `grep`, OR escaping nightmares, OR conditional logic with `[[ ]]` chains — stop, open `script.py`, import `pathlib` + `re` + `subprocess`. The line count will halve and readability will quintuple.

## Parallelization patterns

```bash
# Bounded parallelism via xargs
find . -name '*.py' -print0 \| xargs -0 -P "$(nproc)" -I {} ruff check {}

# Bash background jobs with wait
for url in "${urls[@]}"; do curl -s "$url" > "out/${url//\//_}" & done
wait

# GNU parallel — when xargs isn't enough
parallel -j "$(nproc)" 'echo {}; sleep 1' ::: a b c d e f

# Process substitution to feed two pipes
diff <(cmd1) <(cmd2)
```

### Parallelization anti-patterns

| Pattern | Why bad | Fix |
|---|---|---|
| `for x in ...; do cmd "$x" &; done` (no `wait`) | parent exits before children | `for ...; do cmd &; done; wait` |
| `xargs -P 100 ...` on a 4-core machine | thrashing, not parallelism | `xargs -P "$(nproc)"` |
| Parallel write to one file | interleaved corruption | each writes to its own file; `cat` after |
| Forgetting `set -o pipefail` in parallel scripts | error in `&` job invisible | always set; explicit `wait $pid; rc=$?` per job |

## "Wait for condition" patterns

```bash
# Bad: blind sleep
sleep 10
my_server_should_be_ready

# Good: poll with timeout
timeout 30 bash -c 'until curl -sf localhost:8080/healthz; do sleep 1; done'

# Good: wait for file
timeout 60 bash -c 'until [ -e /tmp/sentinel ]; do sleep 1; done'

# Good: wait for port (no curl)
timeout 30 bash -c 'until (echo > /dev/tcp/localhost/8080) 2>/dev/null; do sleep 1; done'
```

Same rule applies inside CI / hooks / agents: **never sleep when you can poll a condition**.

## Discovery-time integration (when this skill fires)

This skill is consulted (not necessarily loaded in full every time) whenever:

1. An agent is about to chain 3+ shell commands in a pipeline.
2. A grep/find/sed pattern is being authored that would scan a large tree.
3. A bash loop is being written over file paths.
4. A `sleep` is about to be used as a wait.
5. A `cat file \| sed/grep/awk` "useless cat" is about to be written.
6. A `find . -exec ... \;` is about to be written.

It is the canonical companion to the **`kaizen:audit`** flow (which probes code patterns), **`kaizen:review`** flow (which probes diffs), **`kaizen:refactor`** flow (which probes call sites), and the **`kaizen:ast-grep-*`** family (which delegates to ast-grep for syntax-aware searches — this skill covers raw text).

## Anti-pattern: writing a custom script when a kaizen MCP tool exists

Before reaching for a shell pipeline, check:

- `kaizen:loc_search` (file:line lookup over the plugin index)
- `kaizen:onboard_search` (semantic search over the codebase)
- `kaizen:knowledge_search` (semantic search over Notes + audits)
- `kaizen:trace_search` (semantic search over trace events)
- `kaizen:scrape` (web → semantic index)

Each is faster than a hand-rolled grep + post-processing.

## When NOT to load this skill

- Single one-shot command (`ls`, `pwd`, `cat`) — overkill.
- Pure code edits (Edit/Write tools — no shell involved).
- Inside a Python script (use `subprocess.run` with list args; quoting concerns are gone).

## Schema-driven anti-pattern catalog

This skill ships a structured catalog at `domain/anti-patterns.yaml` (validated by `domain/schemas/anti-pattern.schema.json`). Each entry: `id`, `tool`, `bad_pattern`, `why_bad`, `replacement`, `severity`. A future scanner can grep staged scripts against this catalog as a pre-commit check.

## References

- `kaizen:ast-grep-router` — when "search code" is structural (function/class/expr) not textual
- `kaizen:karpathy` — surgical-change discipline (use minimum command-set to achieve the diff)
- `kaizen:verify-before-execution` — every shell command is itself an EXECUTION needing the RED-GREEN gate
- ripgrep manual: https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
- bash strict-mode primer: http://redsymbol.net/articles/unofficial-bash-strict-mode/
- shellcheck: https://www.shellcheck.net/ (run on every script)
