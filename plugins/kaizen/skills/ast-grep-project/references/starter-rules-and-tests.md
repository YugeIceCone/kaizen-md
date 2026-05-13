# Starter Rules & Test Templates
Branch A — pick the language block below. **Copy verbatim** into `<PROJECT>/rules/<filename>.yml`. Do not edit severity or message unless the user asks.

### Rust

**`rules/no-dbg-macro.yml`**:
```yaml
id: no-dbg-macro
language: Rust
severity: error
message: "Leftover dbg!() — remove before committing."
note: "`dbg!()` prints to stderr and ships with the binary. Use `tracing::debug!` or remove."
files:
  - "src/**/*.rs"
  - "examples/**/*.rs"
rule:
  any:
    - pattern: dbg!()
    - pattern: dbg!($$$ARGS)
```

**`rules/no-todo-macro.yml`**:
```yaml
id: no-todo-macro
language: Rust
severity: warning
message: "todo!() / unimplemented!() panics at runtime."
note: "Fine during TDD RED phase. A leftover in committed code is a landmine."
files:
  - "src/**/*.rs"
ignores:
  - "**/tests/**"
  - "**/examples/**"
rule:
  any:
    - pattern: todo!()
    - pattern: todo!($MSG)
    - pattern: unimplemented!()
    - pattern: unimplemented!($MSG)
```

**`rules/no-println-in-lib.yml`**:
```yaml
id: no-println-in-lib
language: Rust
severity: warning
message: "Use `tracing::{info,warn,error,debug}` instead of println!/eprintln! in lib code."
note: "Library crates shouldn't write to stdout/stderr directly. Binaries (src/main.rs, src/bin/*) are the only legitimate println! location."
files:
  - "src/**/*.rs"
ignores:
  - "src/main.rs"
  - "src/bin/**"
  - "**/tests/**"
  - "**/examples/**"
rule:
  any:
    - pattern: println!($$$ARGS)
    - pattern: eprintln!($$$ARGS)
    - pattern: print!($$$ARGS)
    - pattern: eprint!($$$ARGS)
```

### Python

**`rules/no-print-in-lib.yml`**:
```yaml
id: no-print-in-lib
language: Python
severity: warning
message: "Use the `logging` module instead of print() in library code."
note: "Libraries shouldn't emit to stdout; callers may want structured logs or silence."
files:
  - "src/**/*.py"
  - "<PACKAGE>/**/*.py"   # rename to your package dir
ignores:
  - "**/tests/**"
  - "**/test_*.py"
  - "**/__main__.py"
rule:
  pattern: print($$$ARGS)
```

**`rules/no-bare-except.yml`**:
```yaml
id: no-bare-except
language: Python
severity: error
message: "Bare `except:` swallows KeyboardInterrupt / SystemExit. Use `except Exception:` or a specific class."
rule:
  pattern: |
    try:
        $$$BODY
    except:
        $$$HANDLER
```

**`rules/no-mutable-default-arg.yml`**:
```yaml
id: no-mutable-default-arg
language: Python
severity: error
message: "Mutable default argument — shared across calls. Use `None` + `if arg is None: arg = []`."
rule:
  any:
    - pattern: "def $F($$$A, $P=[], $$$B): $$$BODY"
    - pattern: "def $F($$$A, $P={}, $$$B): $$$BODY"
    - pattern: "def $F($$$A, $P=[]): $$$BODY"
    - pattern: "def $F($$$A, $P={}): $$$BODY"
```

### TypeScript / JavaScript

**`rules/no-console-log.yml`** (use `language: TypeScript` for `.ts`/`.tsx`, or `JavaScript` for `.js`/`.jsx`):
```yaml
id: no-console-log
language: TypeScript
severity: warning
message: "Remove console.log before shipping. Use your logger (pino, winston, etc.) instead."
files:
  - "src/**/*.ts"
  - "src/**/*.tsx"
ignores:
  - "**/*.test.ts"
  - "**/*.spec.ts"
rule:
  any:
    - pattern: console.log($$$ARGS)
    - pattern: console.debug($$$ARGS)
```

**`rules/no-any-cast.yml`**:
```yaml
id: no-any-cast
language: TypeScript
severity: warning
message: "Avoid `as any` — it disables type-checking. Use a proper type or `unknown` + narrowing."
files:
  - "src/**/*.ts"
  - "src/**/*.tsx"
rule:
  pattern: $EXPR as any
```

**`rules/no-await-in-loop.yml`**:
```yaml
id: no-await-in-loop
language: TypeScript
severity: warning
message: "Don't await inside loops — serializes work. Use Promise.all over the mapped array."
note: "`for (const x of xs) { await f(x) }` runs sequentially. Prefer `await Promise.all(xs.map(f))`."
rule:
  pattern: await $_
  inside:
    any:
      - kind: for_in_statement
      - kind: for_statement
      - kind: while_statement
    stopBy: end
```

### Go

**`rules/err-must-be-handled.yml`**:
```yaml
id: err-must-be-handled
language: Go
severity: warning
message: "Error return assigned to `_` — handle or propagate it."
rule:
  pattern: _, $_ = $FN($$$ARGS)
```

**`rules/no-fmt-println.yml`**:
```yaml
id: no-fmt-println
language: Go
severity: warning
message: "Use a logger instead of fmt.Println in non-main packages."
files:
  - "**/*.go"
ignores:
  - "**/main.go"
  - "cmd/**"
  - "**/*_test.go"
rule:
  any:
    - pattern: fmt.Println($$$ARGS)
    - pattern: fmt.Printf($$$ARGS)
```

**Done when** — all 3 rule YAML files exist in `<PROJECT>/rules/`.

---

## Step 5 — Tests: one file per rule in `rule-tests/`

Write a test to `<PROJECT>/rule-tests/<rule-id>-test.yml` for every rule in `<PROJECT>/rules/`. Two origins:

- **From Branch A (starter rules)**: use the matching language block below verbatim.
- **From Branch B (pre-existing rules)**: author test cases by reading the existing rule's `pattern:` and `message:`. Format: `id:`, `valid:` (2–3 cases that should NOT trigger), `invalid:` (2–3 cases that SHOULD trigger). Use the language blocks below as shape references, not content.

Snapshot files will land under `<PROJECT>/rule-tests/__snapshots__/` after Step 6 runs — do not create that directory manually.

### Rust test files

**`rule-tests/no-dbg-macro-test.yml`**:
```yaml
id: no-dbg-macro
valid:
  - "fn ok() { let x = 42; println!(\"{x}\"); }"
  - "// dbg!() in a comment is fine"
invalid:
  - "fn bad() { dbg!(); }"
  - "fn bad() { let x = 1; dbg!(x); }"
```

**`rule-tests/no-todo-macro-test.yml`**:
```yaml
id: no-todo-macro
valid:
  - "fn done() -> Result<(), String> { Ok(()) }"
  - "fn propagate() -> Result<(), String> { Err(\"nope\".into()) }"
invalid:
  - "fn leftover() { todo!(); }"
  - "fn leftover_msg() { todo!(\"finish\"); }"
  - "fn u() { unimplemented!(); }"
```

**`rule-tests/no-println-in-lib-test.yml`**:
```yaml
id: no-println-in-lib
valid:
  - "use tracing::info; fn ok() { info!(\"starting\"); }"
  - "fn silent() {}"
invalid:
  - "fn noisy() { println!(\"hello\"); }"
  - "fn noisy() { eprintln!(\"bad\"); }"
```

### Python test files

**`rule-tests/no-print-in-lib-test.yml`**:
```yaml
id: no-print-in-lib
valid:
  - "import logging\nlog = logging.getLogger(__name__)\nlog.info('ok')"
  - "x = 1"
invalid:
  - "print('hello')"
  - "print('x =', 1)"
```

**`rule-tests/no-bare-except-test.yml`**:
```yaml
id: no-bare-except
valid:
  - "try:\n    x = 1\nexcept Exception:\n    pass"
  - "try:\n    x = 1\nexcept ValueError:\n    pass"
invalid:
  - "try:\n    x = 1\nexcept:\n    pass"
```

**`rule-tests/no-mutable-default-arg-test.yml`**:
```yaml
id: no-mutable-default-arg
valid:
  - "def f(xs=None):\n    if xs is None:\n        xs = []\n    return xs"
invalid:
  - "def f(xs=[]):\n    return xs"
  - "def f(d={}):\n    return d"
```

### TypeScript / JavaScript test files

**`rule-tests/no-console-log-test.yml`**:
```yaml
id: no-console-log
valid:
  - "import pino from 'pino'; const log = pino(); log.info('ok')"
  - "const x = 1"
invalid:
  - "console.log('hello')"
  - "console.debug({ x: 1 })"
```

**`rule-tests/no-any-cast-test.yml`**:
```yaml
id: no-any-cast
valid:
  - "const x: unknown = getValue(); if (typeof x === 'string') { console.log(x.length) }"
invalid:
  - "const x = getValue() as any"
  - "const s = (obj as any).field"
```

**`rule-tests/no-await-in-loop-test.yml`**:
```yaml
id: no-await-in-loop
valid:
  - "const xs = await Promise.all(urls.map(fetch))"
  - "async function f() { return await one() }"
invalid:
  - "for (const u of urls) { await fetch(u) }"
  - "while (n--) { await sleep(100) }"
```

### Go test files

**`rule-tests/err-must-be-handled-test.yml`**:
```yaml
id: err-must-be-handled
valid:
  - "x, err := doThing(); if err != nil { return err }"
invalid:
  - "_, _ = doThing()"
```

**`rule-tests/no-fmt-println-test.yml`**:
```yaml
id: no-fmt-println
valid:
  - "log.Info(\"starting\")"
invalid:
  - "fmt.Println(\"hello\")"
  - "fmt.Printf(\"%d\", x)"
```

