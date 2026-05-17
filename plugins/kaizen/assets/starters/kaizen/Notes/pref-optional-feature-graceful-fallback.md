---
name: Optional heavy-dep features must lazy-load with graceful fallback
description: When adding a feature that depends on a heavy or large Python package (transformers, torch, tree-sitter wheels, etc.), wrap it in lazy_load + is_available() + degrade-to-noop. Indexers/search probe is_available and SKIP rather than crash when deps missing.
type: belief
confidence: 0.85
tags: [preference, pattern, python, heavy-deps, indexer-discipline]
sources_count: 4
freshness: stable
created: 2026-05-14
updated: 2026-05-14
---

# Optional heavy-dep features must lazy-load with graceful fallback

Any feature module whose dependencies are HEAVY (large wheel, large
download, optional install) must follow this shape:

```python
_cached = None
_load_attempted = False

def is_<feature>_enabled() -> bool:
    """KAIZEN_<X>_ENABLE in {1, true, yes, on}."""

def _load():
    global _cached, _load_attempted
    if _load_attempted: return _cached
    _load_attempted = True
    try:
        from heavy_dep import Thing
    except ImportError:
        return None
    try:
        _cached = Thing(...)
    except Exception as e:
        sys.stderr.write(f"<feature>: failed: {e}\n")
        return None
    return _cached

def reset_cache() -> None:
    """For tests that mutate env knobs between cases."""

def is_available() -> bool:
    return _load() is not None
```

Callers (indexers / search / chunkers) probe `is_available()` and
RETURN EMPTY (`[]` / `None`) on miss — they NEVER raise, never spam
stderr per-call, never auto-install. The default code path stays
fast + dep-free; the feature is purely additive.

## Why

Big optional deps trip users in three ways:
1. **Install friction** — torch / transformers / tree-sitter-languages
   are 50-500MB. Forcing them on every install kills first-time UX.
2. **Hidden errors** — ImportError mid-indexer with a stack trace
   means the *whole* indexer pipeline crashes when one optional
   feature is missing. Graceful fallback isolates the failure.
3. **Test discipline** — tests that hard-require the dep won't run
   in minimal CI. Mock-friendly modules let pure-logic tests run
   everywhere, model-integration tests skip when deps absent.

Proven 4-for-4 across kaizen-md Phase 4 (2026-05-14):
- E9 (SPLADE — `_sparse.py`)
- E10 (ColBERT — `_colbert.py`)
- O8 (tree-sitter — `_ts_chunk.py`)
- X4 used a stdlib-only path; doesn't apply (counter-example
  shows the shape isn't always needed)

## How to apply

When introducing a new feature module:

1. **Check the dep cost.** > 10MB wheel OR pip-extras territory OR
   non-pure-Python → use this shape. Stdlib-only → don't bother.

2. **Module skeleton** above. Always include `is_available()` AND
   `reset_cache()`. The reset is critical for tests that flip env
   knobs between cases.

3. **Caller pattern** — caller probes `is_available()` early; on
   miss, returns empty (NOT a downgraded result). The indexer
   should treat the column as not-present (skip the population
   entirely), not write a degraded value.

4. **Tests** in three layers:
   - pure-logic (always run): serialize/deserialize, math, env
     handling
   - mocked integration (numpy-only): full indexer flow with a
     monkey-patched encoder
   - real-model (skipped when missing): `@skipUnless(is_available())`

5. **Stderr discipline** — log ONCE on load failure (in `_load()`),
   never per-call. Spam in inner loops is worse than silent skip.

## Common variants

- **Cross-encoder rerank** (kaizen-md `_search.py::_load_cross_encoder`)
  — was the original prototype of this pattern.
- **SPLADE sparse** (`_sparse.py`) — same shape, returns `dict[int, float]`.
- **ColBERT multi-vector** (`_colbert.py`) — same shape, returns matrix.
- **Tree-sitter universal chunker** (`_ts_chunk.py`) — slightly
  different because TS supports many grammars; cached per-grammar.

## Anti-patterns

- ❌ Forcing `pip install` on first call. The dep is a *choice*,
  not an auto-install.
- ❌ `try: import heavy_dep except ImportError: pass` at module top
  — defers the failure to the first attribute access; harder to
  diagnose. Use the lazy `_load()` pattern.
- ❌ Stub-encoder that returns garbage when deps are missing. Worse
  than no result — pollutes the index.
- ❌ Hard `sys.exit(1)` in the indexer when an optional dep is
  missing. Breaks the WHOLE pipeline for ONE optional feature.

## Evidence

- source: kaizen-md commits fa5653c, dfabf72, 1257d11 (2026-05-14)
  description: Phase 4 E9 / E10 / O8 — all four modules implement
    this shape; 122 net new tests gate cleanly on dep availability.
  date: 2026-05-14
