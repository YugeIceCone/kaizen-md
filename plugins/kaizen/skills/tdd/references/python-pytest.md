# Python + pytest Reference

Language-specific patterns for TDD with Python and pytest.

## Test Runner Commands

```bash
# RED: run new tests only
python -m pytest tests/test_my_feature.py -v

# GREEN: run with short traceback
python -m pytest tests/test_my_feature.py -v --tb=short

# REGRESSION: full suite excluding live tests
python -m pytest tests/ -v --tb=short -k "not Live"

# Quick count
python -m pytest tests/ -k "not Live" -q
```

## Mock Strategy — Python/pytest

### Monkeypatch WHERE IMPORTED, not where defined

```python
# WRONG — patches the source module, but consumer already imported the function
monkeypatch.setattr("mylib.core.do_thing", fake)

# RIGHT — patches the local reference in the consuming module
monkeypatch.setattr("myapp.handler.do_thing", fake)
```

### Route mock by prompt content (multi-component flows)

```python
def _route_llm(prompt, **kw):
    if "classify" in prompt:
        return CLASSIFICATION_RESPONSE
    if "evaluate" in prompt:
        return EVALUATION_RESPONSE
    return DEFAULT_RESPONSE
```

### Tier 1.5: Contract-Verified Mocks (autospec)

```python
from unittest.mock import create_autospec

def test_handler_with_verified_mock(monkeypatch):
    from myapp.services import ExternalService
    # create_autospec ensures mock matches real class signature
    # If ExternalService.process() signature changes, this test FAILS
    mock_service = create_autospec(ExternalService, instance=True)
    mock_service.process.return_value = {"status": "ok"}
    monkeypatch.setattr("myapp.handler.ExternalService", lambda: mock_service)
    assert handler.run() == "ok"
```

### Local environment hermeticity

```python
@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Ensure local dev env vars don't leak into tests."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "testing")
```

### File system hermeticity

```python
def test_file_writer(tmp_path):
    """Always use tmp_path — never write to project directories."""
    d = tmp_path / "sub"
    d.mkdir()
    p = d / "hello.txt"
    p.write_text("content")
    assert p.read_text() == "content"
```

### Global state cleanup via autouse fixtures

When modules have module-level flags (debug mode, circuit breakers, singletons),
add cleanup to `conftest.py`:

```python
@pytest.fixture(autouse=True)
def _reset_global_state():
    """Reset module-level state after every test."""
    yield
    # Import and reset each module-level flag
    # Example: my_module.reset_state()
```

## Async Test Patterns

### Standard async test helper

```python
import asyncio

def _run(coro):
    """Run async code in tests without pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
```

### Concurrency verification (semaphore bounds)

```python
peak, current = {"value": 0}, {"value": 0}

async def _tracking_fn(*args, **kw):
    current["value"] += 1
    peak["value"] = max(peak["value"], current["value"])
    await asyncio.sleep(0.01)  # simulate work
    current["value"] -= 1
    return "result"

# After test:
assert peak["value"] <= max_concurrent
```

### Benchmark safety

- NEVER `asyncio.run()` inside benchmark loops — create one event_loop_runner fixture, reuse `loop.run_until_complete()`
- ALWAYS clamp overlap parameters to prevent infinite loops: `overlap = min(overlap, size - 1)`
- Default benchmarks to skip: `addopts = "--benchmark-skip"` in pyproject.toml
- Cap calibration: `--benchmark-min-rounds=3 --benchmark-max-time=0.5`

## Stub Pattern for RED Phase

Use try/except import so tests can be discovered before implementation:

```python
try:
    from mypackage.impl import my_function
except ImportError:
    def my_function(*args, **kwargs):
        raise NotImplementedError("Implement in mypackage/impl.py")
```

## Property-Based Testing (Hypothesis)

```python
from hypothesis import given, strategies as st

@given(st.text(), st.text())
def test_encode_decode_roundtrip(key, value):
    """Invariant: decode(encode(x)) == x for all valid inputs."""
    encoded = encode(key, value)
    decoded = decode(encoded)
    assert decoded == (key, value)

@given(st.lists(st.integers()))
def test_sort_preserves_length(data):
    assert len(my_sort(data)) == len(data)

@given(st.integers(min_value=1, max_value=10000))
def test_chunk_size_bounded(size):
    chunks = chunk_by_chars("x" * size, chars_per_chunk=100)
    assert all(len(c) <= 120 for c in chunks)  # boundary slack
```

Install: `pip install hypothesis`

## Mutation Testing

```bash
# Install
pip install mutmut

# Run against specific test file
mutmut run --paths-to-mutate=src/mymodule.py --tests-dir=tests/

# Show surviving mutants
mutmut results

# Show specific mutant
mutmut show 42
```

Target >90% kill rate on changed code. Surviving mutants = missing assertions.

## Live Verification Pattern

After mocked tests pass, verify against real backends:

```python
import pytest

requires_backend = pytest.mark.skipif(
    not _backend_available(), reason="Backend not running"
)

@requires_backend
class TestLiveIntegration:
    def test_real_endpoint(self):
        result = real_api_call("test")
        assert result is not None
```
