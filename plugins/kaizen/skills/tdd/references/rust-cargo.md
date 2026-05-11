# Rust + cargo Reference

Language-specific patterns for TDD with Rust and cargo. Load alongside the top-level `tdd` skill's workflow — this file covers Rust-idiomatic test mechanics, mocking, and CI speed.

## Where Rust tests live

Rust is unusual: the same crate has **four** test surfaces, each with different rules. Put tests in the right place — moving them later breaks the visibility contract.

- **Unit tests** — inline in the source file inside a `#[cfg(test)] mod tests { ... }` block. Can reach private items via `use super::*;`. Compiled only when running tests. This is the default home for Tier 1 tests.
- **Integration tests** — one file per scenario in `tests/<name>.rs`. Each file is its own compiled crate that links against the library's **public API only**. Use this for Tier 2 contract tests.
- **Shared test helpers** — `tests/common/mod.rs` (NOT `tests/common.rs`, which cargo would treat as its own test file). Declare with `mod common;` from the integration test file that needs it.
- **Doctests** — examples inside `///` doc comments. Executed by `cargo test --doc`. Treat them as Tier 2 API-contract tests — the public API you promise in the docs must work.

```rust
// src/lib.rs — unit test inside the same file
pub fn parse(input: &str) -> Result<Payload, ParseError> {
    // ...
}

#[cfg(test)]
mod tests {
    use super::*;   // access private items

    #[test]
    fn rejects_empty_input() {
        assert!(matches!(parse(""), Err(ParseError::Empty)));
    }
}
```

```rust
// tests/api.rs — integration test, sees only the public API
use my_crate::parse;

#[test]
fn round_trip_hello() {
    let p = parse("hello").unwrap();
    assert_eq!(p.render(), "hello");
}
```

```rust
/// Parses `input` into a `Payload`.
///
/// # Examples
/// ```
/// let p = my_crate::parse("hi").unwrap();
/// assert_eq!(p.render(), "hi");
/// ```
pub fn parse(input: &str) -> Result<Payload, ParseError> { /* ... */ }
```

## Test Runner Commands

```bash
# RED: run one new integration file only
cargo test --test my_feature

# RED: run one unit-test module by path
cargo test my_module::tests

# GREEN: quiet output while iterating
cargo test --test my_feature -- --quiet

# REGRESSION: full suite — unit + integration + doctests
cargo test --all-features

# REGRESSION (fast): nextest runs 60% faster than cargo test on most workspaces
cargo nextest run --all-features

# Quick count (cargo test only — nextest has its own summary)
cargo test --all-features 2>&1 | tail -5

# See println! / dbg! output from passing tests
cargo test -- --nocapture

# Run a single test by exact name
cargo test --test my_feature -- exact_test_name --exact

# Skip tests marked #[ignore] (default) or run only ignored ones
cargo test                      # default: skips #[ignore]
cargo test -- --ignored         # run only ignored
cargo test -- --include-ignored # run both

# Doctests only
cargo test --doc

# Lib tests only, skipping integration
cargo test --lib
```

**The `--` separator is load-bearing.** Everything before `--` is interpreted by cargo; everything after is passed to the test binary. Forgetting it silently ignores test-binary flags.

## Parallelism — the single biggest speed win

Cargo auto-parallelizes tests, but CI runners are often under-used because the test binary can't probe the container's CPU quota reliably. Force it:

```bash
THREADS=$(nproc)
cargo test --all-features -- --test-threads=${THREADS}
```

Reported result in practice: **2–3× faster on multi-core CI runners** that weren't saturated before. No code changes required.

Reverse direction — **serial execution** when tests touch shared external state (ports, filesystem paths under a fixed name, process-global env vars):

```bash
cargo test -- --test-threads=1
```

Or keep parallel overall and mark only the few serial-only tests with the `serial_test` crate:

```rust
use serial_test::serial;

#[test]
#[serial]
fn mutates_env_var() {
    std::env::set_var("MY_VAR", "value");   // safe: no parallel test touches MY_VAR
    // ...
}
```

## Hermeticity

Rust's strictest rule: **no shared mutable state between tests**. Tests run in parallel by default across threads inside one process — any `static mut`, any `lazy_static!` with interior mutability, any `std::env::set_var` will race.

### Per-test fixtures, not globals

```rust
// WRONG — shared, races under parallel test runner
static REPO: once_cell::sync::Lazy<Repo> = once_cell::sync::Lazy::new(Repo::new);

#[test] fn a() { REPO.insert("x"); /* ... */ }
#[test] fn b() { REPO.insert("y"); /* ... */ }

// RIGHT — each test builds its own
fn make_repo() -> Repo { Repo::new() }

#[test] fn a() { let repo = make_repo(); repo.insert("x"); }
#[test] fn b() { let repo = make_repo(); repo.insert("y"); }
```

### Read-only shared state via `OnceLock` is fine

Read-only precomputed state doesn't race because there are no writes after the single initialization:

```rust
use std::sync::OnceLock;

static FIXTURE: OnceLock<Fixture> = OnceLock::new();

fn get_fixture() -> &'static Fixture {
    FIXTURE.get_or_init(|| load_expensive_fixture_once())
}
```

Use this when the setup cost is high and every test would otherwise re-parse the same file / rebuild the same graph. Never mutate through the returned reference.

### File system — always `tempfile`

```rust
use tempfile::tempdir;

#[test]
fn writes_output_file() {
    let dir = tempdir().unwrap();              // dropped at end → auto-cleanup
    let path = dir.path().join("output.txt");
    std::fs::write(&path, b"content").unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), b"content");
}
```

**Never write to the project directory** — not `./target/test-output/`, not `./logs/`, not `./tmp/`. `tempfile::tempdir()` returns a drop-guarded directory under the OS temp path; files vanish when the guard goes out of scope.

### Env var mutation needs serialization

`std::env::set_var` is process-global, `unsafe` as of Rust 1.80+. Under parallel test runners it races unconditionally. Two strategies:

```rust
// Strategy 1: gate the whole test binary to one thread — simplest, slowest
// in Cargo.toml test config or via: cargo test -- --test-threads=1

// Strategy 2: serialize only the env-touching tests with serial_test
use serial_test::serial;

#[test]
#[serial]
fn config_reads_env() {
    // SAFETY: serial_test ensures no other test runs concurrently.
    unsafe { std::env::set_var("APP_URL", "http://localhost:8080"); }
    // ...
    unsafe { std::env::remove_var("APP_URL"); }
}
```

Strategy 2 keeps the rest of the suite parallel. Prefer it when only a handful of tests touch env vars.

## Mock Strategy — Rust

Rust's type system is the first line of defense. `mockall` is the standard trait-based mocking crate when you need runtime polymorphism; for everything else, construct a fake implementation of the trait directly.

### Tier 1.5: Contract-verified mocks via `mockall::automock`

`#[automock]` generates a mock struct whose signatures are compile-checked against the trait. If the real trait's signature changes, the mock **fails to compile** — exactly what Tier 1.5 mandates.

```rust
// src/service.rs
use mockall::automock;

#[automock]
pub trait ExternalService: Send + Sync {
    fn process(&self, input: &str) -> Result<String, ServiceError>;
}
```

```rust
// tests/handler.rs
use my_crate::service::MockExternalService;

#[test]
fn handler_returns_ok_on_successful_process() {
    let mut mock = MockExternalService::new();
    mock.expect_process()
        .withf(|input| input == "ping")
        .times(1)
        .returning(|_| Ok("pong".to_string()));

    let handler = Handler::new(Box::new(mock));
    assert_eq!(handler.run("ping").unwrap(), "pong");
    // `times(1)` + mock drop = compile-check the call actually happened
}
```

Install: `cargo add --dev mockall`

### Route mock by input content (multi-call flows)

```rust
let mut mock = MockLlmClient::new();
mock.expect_generate()
    .returning(|prompt| {
        if prompt.contains("classify") { Ok(CLASSIFICATION.into()) }
        else if prompt.contains("evaluate") { Ok(EVALUATION.into()) }
        else { Ok(DEFAULT_RESPONSE.into()) }
    });
```

### Fake implementations (no mock library needed)

When a trait is small and stable, write a fake struct directly. Cheaper than mockall, clearer in diffs, survives trait refactors without codegen churn:

```rust
struct InMemoryRepo { inner: std::sync::Mutex<Vec<Item>> }

impl Repository for InMemoryRepo {
    fn save(&self, item: Item) { self.inner.lock().unwrap().push(item); }
    fn find(&self, id: u64) -> Option<Item> { /* ... */ }
}

#[test]
fn saves_then_finds() {
    let repo = InMemoryRepo { inner: Default::default() };
    repo.save(Item::new(1, "hi"));
    assert!(repo.find(1).is_some());
}
```

**Mock at the trait boundary.** Rust's equivalent of "patch at the system boundary" is "introduce a trait at the boundary, pass `Box<dyn Trait>` (or a generic parameter), mock the trait in tests, use the real impl in prod."

## Stub Pattern for RED Phase

Rust's compiler is the RED signal. Write the test; it won't compile until the type or function exists. Then write a stub that compiles but fails at runtime:

```rust
// src/feature.rs — the compile-fails-to-pass stub
pub fn compute(input: &Input) -> Result<Output, MyError> {
    todo!("implement compute — see tests/compute.rs")
    // `todo!()` returns `!`, so this type-checks whatever the signature demands.
    // At runtime the test panics with a clear "not yet implemented" message.
}
```

Alternatives when `todo!()` is the wrong shape:

- `unimplemented!()` — same runtime behavior, semantic nuance of "this branch intentionally unreachable for now"
- `compile_error!("stub")` — blocks compilation entirely, forcing the next session to notice
- `return Err(MyError::NotImplemented)` — when you want the test to observe a specific error variant

Never `#[allow(dead_code)]` a stub — leave cargo's "unused function" warning in place as a reminder.

## Async Test Patterns

### `#[tokio::test]` — one runtime per test

```rust
#[tokio::test]
async fn fetches_from_local_endpoint() {
    let result = client::fetch("http://localhost:8080/status").await.unwrap();
    assert!(result.contains("ok"));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn spawns_two_concurrent_tasks() {
    let (a, b) = tokio::join!(task_a(), task_b());
    assert!(a.is_ok() && b.is_ok());
}
```

Default flavor is single-threaded — prefer it unless the test genuinely needs real thread parallelism. Single-threaded runtimes are faster to spin up and deterministic.

### Deadline every `.await` that touches I/O

```rust
use tokio::time::{timeout, Duration};

#[tokio::test]
async fn request_completes_within_bounded_time() {
    let result = timeout(Duration::from_secs(5), client.fetch(url))
        .await
        .expect("timed out — network stall or stuck task")
        .unwrap();
    assert!(!result.is_empty());
}
```

A test that waits forever is worse than a flaky test — it hangs CI without a signal. Every async I/O test in the suite should have a `timeout` guard.

### Concurrency verification

```rust
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

#[tokio::test]
async fn never_exceeds_three_concurrent_calls() {
    let current = Arc::new(AtomicUsize::new(0));
    let peak = Arc::new(AtomicUsize::new(0));

    let mut handles = vec![];
    for _ in 0..10 {
        let cur = Arc::clone(&current);
        let pk = Arc::clone(&peak);
        handles.push(tokio::spawn(async move {
            let now = cur.fetch_add(1, Ordering::SeqCst) + 1;
            pk.fetch_max(now, Ordering::SeqCst);
            tokio::time::sleep(Duration::from_millis(10)).await;
            cur.fetch_sub(1, Ordering::SeqCst);
        }));
    }
    for h in handles { h.await.unwrap(); }

    assert!(peak.load(Ordering::SeqCst) <= 3, "concurrency bound violated");
}
```

### Never spawn detached tasks that outlive the test

```rust
// WRONG — leaks a task that keeps running after the test ends
tokio::spawn(async { loop { check_health().await; } });

// RIGHT — JoinHandle is awaited or a CancellationToken aborts it
let handle = tokio::spawn(async { /* ... */ });
// assert ...
handle.abort();
let _ = handle.await;
```

## Property-Based Testing (proptest)

`proptest` is the Rust-idiomatic PBT crate. `quickcheck` exists too but has less active development; prefer proptest for new code.

```rust
use proptest::prelude::*;

proptest! {
    #[test]
    fn encode_then_decode_is_identity(s in ".*") {
        let encoded = encode(&s);
        prop_assert_eq!(decode(&encoded).unwrap(), s);
    }

    #[test]
    fn sort_preserves_length(v in prop::collection::vec(any::<i32>(), 0..1000)) {
        let sorted = my_sort(&v);
        prop_assert_eq!(sorted.len(), v.len());
    }

    #[test]
    fn chunk_size_is_bounded(
        size in 1usize..10_000,
        chunk_size in 1usize..1_000,
    ) {
        let input = "x".repeat(size);
        let chunks = chunk_by_chars(&input, chunk_size);
        prop_assert!(chunks.iter().all(|c| c.len() <= chunk_size + 20));
    }
}
```

Install: `cargo add --dev proptest`

**Shrinking comes for free.** When proptest finds a counterexample, it automatically shrinks to the minimal failing input — often a single character or empty vec. Read the shrunk case, not the original.

## Snapshot Testing (insta)

`insta` is the standard snapshot tool. Use when the output is structured but verbose — rendered AST, serialized JSON, formatted error message — and a string-level assertion would be too noisy.

```rust
use insta::{assert_debug_snapshot, assert_yaml_snapshot};

#[test]
fn parse_produces_expected_ast() {
    let ast = parse("let x = 1 + 2;").unwrap();
    assert_debug_snapshot!(ast);
}

#[test]
fn error_shape_is_stable() {
    let err = parse("let =").unwrap_err();
    assert_yaml_snapshot!(err, @r###"
    kind: UnexpectedToken
    position: 4
    expected: identifier
    "###);
}
```

Workflow: write test → run → insta writes `.snap.new` → review with `cargo insta review` → accept or reject. On CI, snapshots are asserted as-is; on a dev machine, you get the review loop.

Install: `cargo add --dev insta`; optional: `cargo install cargo-insta`

## Mutation Testing (cargo-mutants)

```bash
# Install once
cargo install cargo-mutants

# Run across the whole crate
cargo mutants

# Scope to changed files only (fast iteration)
cargo mutants --in-diff origin/main

# Scope to a specific file
cargo mutants --file src/parser.rs
```

`cargo-mutants` injects deliberate faults (`==` → `!=`, `+` → `-`, skip return values) and re-runs the test suite. A surviving mutant means the suite could not distinguish the mutated code from the real code — a missing assertion. Target >90% kill rate on changed code.

Slow by design — mutation testing runs your entire suite N times. Scope with `--in-diff` during TDD iteration and save full runs for pre-merge gates.

## Fuzz Testing (cargo-fuzz)

For parsers, deserializers, and any code that consumes untrusted bytes. Overkill for business logic; essential for trust boundaries.

```bash
cargo install cargo-fuzz
cargo fuzz init
cargo fuzz add parse_input
cargo fuzz run parse_input
```

```rust
// fuzz/fuzz_targets/parse_input.rs
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = my_crate::parse_bytes(data);  // must not panic on any input
});
```

Requires nightly (`rustup install nightly`, `cargo +nightly fuzz run`).

## Coverage (cargo-llvm-cov)

```bash
# Install
cargo install cargo-llvm-cov

# HTML report
cargo llvm-cov --html --open

# Lcov for CI (Codecov, Coveralls, etc.)
cargo llvm-cov --lcov --output-path lcov.info

# Gate: fail CI if coverage drops below a threshold
cargo llvm-cov --fail-under-lines 80
```

Prefer `cargo-llvm-cov` over `cargo-tarpaulin` — llvm-cov uses the source-based instrumentation built into rustc, runs faster, and handles generics + inlined code correctly. Tarpaulin is older, has known blind spots in generic code, and should be treated as legacy.

## Doctests — the cheapest integration test

Every `/// # Examples` block inside a `///` doc comment runs as a test when you invoke `cargo test --doc`. Treat each doctest as a public-API contract:

```rust
/// Trims whitespace and returns `None` for empty strings.
///
/// # Examples
///
/// ```
/// use my_crate::trim_to_option;
/// assert_eq!(trim_to_option("  hello  "), Some("hello".to_string()));
/// assert_eq!(trim_to_option("   "), None);
/// ```
pub fn trim_to_option(input: &str) -> Option<String> { /* ... */ }
```

If the example stops compiling or the assertion stops holding, `cargo test --doc` fails — which means the docs and the code can't drift. Every public function deserves at least one doctest illustrating the happy path.

Skip doctests in fast-iteration loops (`cargo test --lib --tests` skips `--doc`); include them in the regression gate.

## CI Speed — the Rust-specific wins

Rust's compile time is the elephant in every CI room. The patterns below compound — apply all that fit your workflow.

### 1. `cargo nextest run` instead of `cargo test`

Nextest reuses test binaries across runs, parallelizes per-test rather than per-binary, and provides better failure output. Typical speedup: **60% faster** on workspaces with many integration test files.

```bash
cargo install cargo-nextest
cargo nextest run --all-features
```

Doctests are not run by nextest — still use `cargo test --doc` for those, or gate doctests as a separate CI job.

### 2. Explicit `--test-threads=$(nproc)`

Already covered above. Biggest single win on under-utilized CI runners.

### 3. Cache `target/` between CI runs

Keyed on `Cargo.lock`. Using GitHub Actions:

```yaml
- uses: actions/cache@v4
  with:
    path: |
      ~/.cargo/registry
      ~/.cargo/git
      target
    key: ${{ runner.os }}-cargo-${{ hashFiles('**/Cargo.lock') }}
    restore-keys: ${{ runner.os }}-cargo-
```

Caveat: `target/` caches bloat fast. Prune aggressively with `cargo sweep` or recreate the key on major version bumps.

### 4. Faster linker — `mold` (Linux) or `lld` (cross-platform)

Linking dominates build time on large Rust projects. Install `mold` in the CI image and point rustc at it:

```toml
# .cargo/config.toml
[target.x86_64-unknown-linux-gnu]
linker = "clang"
rustflags = ["-C", "link-arg=-fuse-ld=mold"]
```

Typical improvement: 30-50% faster link step on medium workspaces.

### 5. Disable incremental builds in CI

Incremental compilation helps on dev machines (where the same files are edited repeatedly) and hurts in CI (where every run is cold). Disable it:

```bash
export CARGO_INCREMENTAL=0
```

Or in the workflow env block. Reduces total build time and shrinks `target/` cache size.

### 6. Use `sccache` for cross-job rustc caching

When the same dependencies are compiled across many jobs (matrix builds, PR re-runs), `sccache` deduplicates at the compiler level:

```bash
export RUSTC_WRAPPER=sccache
export SCCACHE_DIR=$HOME/.cache/sccache
```

GitHub Actions: use `mozilla-actions/sccache-action` to wire it in.

### 7. Split check + test + build in parallel CI jobs

```yaml
jobs:
  fmt:    cargo fmt --check
  clippy: cargo clippy --all-features -- -D warnings
  check:  cargo check --all-features
  test:   cargo nextest run --all-features
  doc:    cargo test --doc
```

Each runs in parallel on separate runners. The slowest job dictates wall clock; individual cache hit rates stay high because every job touches a predictable subset of `target/`.

### 8. `--profile=ci` — a custom lean profile

```toml
# Cargo.toml
[profile.ci]
inherits = "dev"
debug = 0            # no debug info — smaller artifacts, faster link
incremental = false  # already off via env, but belt-and-braces
```

Then: `cargo nextest run --profile=ci`. Trade debug symbols (unused in green runs) for speed.

### 9. Workspace-aware test scoping

On a big monorepo, run only the affected crate:

```bash
# Run tests only in crates that changed since origin/main
cargo nextest run -p crate-that-changed
```

Combine with path filters in the CI trigger so a markdown edit doesn't rebuild Rust.

## Live Verification Pattern

After mocked tests pass, verify against real backends. Guard with an env-var or feature flag so CI doesn't hit external services on every run:

```rust
fn live_backend_available() -> bool {
    std::env::var("LIVE_BACKEND").is_ok()
}

#[test]
fn hits_real_api() {
    if !live_backend_available() {
        eprintln!("SKIPPED: set LIVE_BACKEND=1 to run");
        return;
    }
    let client = Client::new(std::env::var("LIVE_BACKEND_URL").unwrap());
    let result = client.fetch("/status").unwrap();
    assert!(!result.is_empty());
}
```

Run live tests manually or in a dedicated nightly CI job — never in the fast loop.

## Regression gates (for this crate's Phase 4)

Before declaring a TDD task complete, run every gate that applies:

```bash
cargo fmt --check
cargo clippy --all-features -- -D warnings
cargo check --all-features
cargo nextest run --all-features  # or: cargo test --all-features
cargo test --doc
```

Zero failures across all five. If any gate produces warnings, fix them — do not `#[allow(...)]` them away unless the reason is documented in the surrounding code. This matches the top-level `tdd` skill's Phase 4 rule: "Full existing suite — zero failures."

## Quick reference: common crates

- **mockall** — trait mocking with `#[automock]`; the Tier 1.5 equivalent
- **proptest** — property-based testing, shrinking
- **insta** — snapshot assertions with review workflow
- **serial_test** — gate individual tests to serial execution
- **tempfile** — drop-guarded temp directories and files
- **rstest** — parameterized tests + fixtures (optional but handy)
- **cargo-nextest** — faster test runner (binary)
- **cargo-mutants** — mutation testing (binary)
- **cargo-llvm-cov** — coverage (binary)
- **cargo-fuzz** — fuzz testing (binary, needs nightly)
- **criterion** — statistical benchmarks (goes in `benches/`, not `tests/`)
