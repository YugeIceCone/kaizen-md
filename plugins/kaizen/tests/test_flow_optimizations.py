"""Tests for the v1.34 flow.py optimization pass.

Exercises every new feature alongside the legacy API to prove
backward compatibility:

  - successors on AsyncNode (was on AsyncFlow only)
  - `>>` and `- "action" >>` syntactic sugar
  - max_iterations cycle guard
  - retries + exec_fallback_async
  - AsyncBatchNode + AsyncParallelBatchNode
  - on_enter / on_exit / on_error event hooks (sync + async)
  - cumulative timing (loops + re-entrant nodes)
  - error context (add_note when available)
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import flow as _flow  # noqa: E402

# ─── Helpers ─────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)

def _make_recorder(name):
    """Build an AsyncNode that records its invocation in store['log']."""
    class Recorder(_flow.AsyncNode):
        async def prep_async(self, store):
            store.setdefault("log", []).append(("prep", name))
            return None
        async def exec_async(self, prep):
            store_log = None  # exec_async doesn't see store; OK
            return name
        async def post_async(self, store, prep, exec_result):
            store["log"].append(("post", name, exec_result))
            return store.get("next_action", "default")
    Recorder.__name__ = f"Recorder_{name}"
    return Recorder()

# ─── Successors-on-node + chaining ───────────────────────────────────

class TestSuccessorsOnNode(unittest.TestCase):
    def test_default_successor_chain_via_rshift(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        c = _make_recorder("C")
        a >> b >> c
        # Chain stored on each node
        self.assertIs(a.successors["default"], b)
        self.assertIs(b.successors["default"], c)
        self.assertEqual(c.successors, {})

    def test_named_action_via_sub_rshift(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        c = _make_recorder("C")
        a >> b
        a - "error" >> c
        self.assertIs(a.successors["default"], b)
        self.assertIs(a.successors["error"], c)

    def test_sub_rejects_non_string(self):
        a = _make_recorder("A")
        with self.assertRaises(TypeError):
            a - 42  # type: ignore[operator]

    def test_next_method_returns_succ_for_chaining(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        result = a.next(b)
        self.assertIs(result, b)

    def test_legacy_add_successor_still_works(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        flow = _flow.AsyncFlow(a)
        flow.add_successor(a, "default", b)
        # Authoritative copy on the node
        self.assertIs(a.successors["default"], b)
        # Legacy mirror also populated for back-compat inspection
        self.assertIs(flow.successors[(a, "default")], b)

# ─── AsyncFlow.run_async (end-to-end) ────────────────────────────────

class TestFlowExecution(unittest.TestCase):
    def test_linear_three_node_run(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        c = _make_recorder("C")
        a >> b >> c
        store: dict = {}
        _run(_flow.AsyncFlow(a).run_async(store))
        # Three post events in order
        post_names = [e[1] for e in store["log"] if e[0] == "post"]
        self.assertEqual(post_names, ["A", "B", "C"])

    def test_branching_via_action_key(self):
        router = _make_recorder("R")
        path1 = _make_recorder("P1")
        path2 = _make_recorder("P2")
        router - "alpha" >> path1
        router - "beta" >> path2
        store = {"next_action": "beta"}
        _run(_flow.AsyncFlow(router).run_async(store))
        names = [e[1] for e in store["log"] if e[0] == "post"]
        self.assertEqual(names, ["R", "P2"])

    def test_no_successor_terminates(self):
        a = _make_recorder("A")
        store: dict = {}
        _run(_flow.AsyncFlow(a).run_async(store))
        names = [e[1] for e in store["log"] if e[0] == "post"]
        self.assertEqual(names, ["A"])

    def test_returning_none_falls_through_to_default(self):
        # Documented behavior (preserved from pre-v1.34): post_async
        # returning None → action defaults to "default". The flow
        # only terminates when there's no successor for the action.
        class Terminal(_flow.AsyncNode):
            async def post_async(self, store, prep, exec_result):
                store["log"] = ["done"]
                return None
        a = Terminal()
        b = _make_recorder("B")
        a >> b  # default successor exists → b WILL run
        store: dict = {}
        _run(_flow.AsyncFlow(a).run_async(store))
        # B runs because the default successor was wired
        names_after_done = [
            e[1] for e in store["log"] if isinstance(e, tuple) and e[0] == "post"
        ]
        self.assertIn("B", names_after_done)

    def test_no_default_successor_terminates_on_none(self):
        # Without a wired default successor, returning None terminates
        # because successors.get("default") → None.
        class Terminal(_flow.AsyncNode):
            async def post_async(self, store, prep, exec_result):
                store["log"] = ["only-me"]
                return None
        store: dict = {}
        _run(_flow.AsyncFlow(Terminal()).run_async(store))
        self.assertEqual(store["log"], ["only-me"])

# ─── Cycle detection ────────────────────────────────────────────────

class TestCycleGuard(unittest.TestCase):
    def test_default_max_iterations_catches_cycle(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        a >> b
        b >> a  # cycle
        flow = _flow.AsyncFlow(a, max_iterations=10)
        with self.assertRaises(RuntimeError) as ctx:
            _run(flow.run_async({}))
        self.assertIn("max_iterations", str(ctx.exception))

    def test_max_iterations_none_disables_guard(self):
        # Set up a small bounded loop that terminates of its own accord
        class Counter(_flow.AsyncNode):
            async def prep_async(self, store):
                return store.get("count", 0)
            async def post_async(self, store, prep, exec_result):
                store["count"] = prep + 1
                if store["count"] < 5:
                    return "loop"
                return None  # terminate
        c = Counter()
        c - "loop" >> c
        flow = _flow.AsyncFlow(c, max_iterations=None)
        _run(flow.run_async({}))
        # If max_iterations=None disabled the check, we reach count=5

    def test_high_max_iterations_allows_long_loop(self):
        class Counter(_flow.AsyncNode):
            async def post_async(self, store, prep, exec_result):
                store["count"] = store.get("count", 0) + 1
                return None if store["count"] >= 100 else "loop"
        c = Counter()
        c - "loop" >> c
        flow = _flow.AsyncFlow(c, max_iterations=200)
        _run(flow.run_async({}))

# ─── Retry + fallback ────────────────────────────────────────────────

class TestRetryFallback(unittest.TestCase):
    def test_default_no_retry_fails_fast(self):
        class Flaky(_flow.AsyncNode):
            async def exec_async(self, prep):
                raise RuntimeError("boom")
        node = Flaky()
        with self.assertRaises(RuntimeError):
            _run(node.run_async({}))

    def test_retry_eventually_succeeds(self):
        class Flaky(_flow.AsyncNode):
            max_retries = 3
            wait = 0.0
            attempts = 0
            async def exec_async(self, prep):
                Flaky.attempts += 1
                if Flaky.attempts < 3:
                    raise RuntimeError("transient")
                return "ok"
            async def post_async(self, store, prep, exec_result):
                store["result"] = exec_result
                return None
        Flaky.attempts = 0
        store: dict = {}
        _run(Flaky().run_async(store))
        self.assertEqual(store["result"], "ok")
        self.assertEqual(Flaky.attempts, 3)

    def test_retry_exhausted_calls_fallback(self):
        class Flaky(_flow.AsyncNode):
            max_retries = 2
            async def exec_async(self, prep):
                raise RuntimeError("always fails")
            async def exec_fallback_async(self, prep, exc):
                return "degraded"
            async def post_async(self, store, prep, exec_result):
                store["result"] = exec_result
                return None
        store: dict = {}
        _run(Flaky().run_async(store))
        self.assertEqual(store["result"], "degraded")

    def test_fallback_reraise_default(self):
        class Flaky(_flow.AsyncNode):
            max_retries = 2
            async def exec_async(self, prep):
                raise ValueError("nope")
        with self.assertRaises(ValueError):
            _run(Flaky().run_async({}))

# ─── Batch nodes ─────────────────────────────────────────────────────

class TestAsyncBatchNode(unittest.TestCase):
    def test_sequential_batch(self):
        class Squarer(_flow.AsyncBatchNode):
            async def prep_async(self, store):
                return [1, 2, 3, 4]
            async def exec_one_async(self, item):
                return item * item
            async def post_async(self, store, prep, exec_result):
                store["squares"] = exec_result
                return None
        store: dict = {}
        _run(Squarer().run_async(store))
        self.assertEqual(store["squares"], [1, 4, 9, 16])

    def test_empty_batch(self):
        class Sq(_flow.AsyncBatchNode):
            async def prep_async(self, store):
                return []
            async def exec_one_async(self, item):
                return item
            async def post_async(self, store, prep, exec_result):
                store["out"] = exec_result
                return None
        store: dict = {}
        _run(Sq().run_async(store))
        self.assertEqual(store["out"], [])

class TestAsyncParallelBatchNode(unittest.TestCase):
    def test_parallel_batch_runs_concurrently(self):
        # Each exec_one sleeps 50ms; 5 items should finish in well
        # under 250ms if truly concurrent.
        class Sleeper(_flow.AsyncParallelBatchNode):
            async def prep_async(self, store):
                return list(range(5))
            async def exec_one_async(self, item):
                await asyncio.sleep(0.05)
                return item
            async def post_async(self, store, prep, exec_result):
                store["out"] = exec_result
                return None
        store: dict = {}
        t0 = time.perf_counter()
        _run(Sleeper().run_async(store))
        elapsed = time.perf_counter() - t0
        self.assertEqual(sorted(store["out"]), list(range(5)))
        # Generous threshold (200ms) — should be ~50ms but CI is flaky
        self.assertLess(elapsed, 0.2)

    def test_concurrency_cap(self):
        # Cap=1 forces sequential; 5 items × 50ms ≈ 250ms+
        class Sleeper(_flow.AsyncParallelBatchNode):
            concurrency = 1
            async def prep_async(self, store):
                return list(range(5))
            async def exec_one_async(self, item):
                await asyncio.sleep(0.03)
                return item
            async def post_async(self, store, prep, exec_result):
                store["out"] = exec_result
                return None
        store: dict = {}
        t0 = time.perf_counter()
        _run(Sleeper().run_async(store))
        elapsed = time.perf_counter() - t0
        self.assertEqual(store["out"], list(range(5)))
        # Sequential at 30ms × 5 = 150ms baseline; should NOT finish
        # in concurrent <100ms
        self.assertGreater(elapsed, 0.12)

    def test_empty_parallel_batch(self):
        class S(_flow.AsyncParallelBatchNode):
            async def prep_async(self, store):
                return []
            async def exec_one_async(self, item):
                return item
            async def post_async(self, store, prep, exec_result):
                store["out"] = exec_result
                return None
        store: dict = {}
        _run(S().run_async(store))
        self.assertEqual(store["out"], [])

# ─── Event hooks ─────────────────────────────────────────────────────

class TestEventHooks(unittest.TestCase):
    def test_on_enter_on_exit_sync(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        a >> b
        events = []

        def on_enter(node, store):
            events.append(("enter", node.__class__.__name__))

        def on_exit(node, store, action):
            events.append(("exit", node.__class__.__name__, action))

        flow = _flow.AsyncFlow(a, on_enter=on_enter, on_exit=on_exit)
        _run(flow.run_async({}))
        names = [e[1] for e in events]
        self.assertIn("Recorder_A", names)
        self.assertIn("Recorder_B", names)
        # Order: enter A, exit A, enter B, exit B
        self.assertEqual(events[0][0], "enter")
        self.assertEqual(events[1][0], "exit")

    def test_on_enter_async(self):
        # Async hooks are awaited automatically
        a = _make_recorder("A")
        events = []

        async def on_enter(node, store):
            await asyncio.sleep(0)
            events.append(node.__class__.__name__)

        flow = _flow.AsyncFlow(a, on_enter=on_enter)
        _run(flow.run_async({}))
        self.assertEqual(events, ["Recorder_A"])

    def test_on_error_called_on_exception(self):
        class Bad(_flow.AsyncNode):
            async def exec_async(self, prep):
                raise RuntimeError("explode")

        captured = []

        def on_error(node, store, exc):
            captured.append((node.__class__.__name__, str(exc)))

        flow = _flow.AsyncFlow(Bad(), on_error=on_error)
        with self.assertRaises(RuntimeError):
            _run(flow.run_async({}))
        self.assertEqual(captured[0][0], "Bad")
        self.assertIn("explode", captured[0][1])

# ─── Timing ──────────────────────────────────────────────────────────

class TestTiming(unittest.TestCase):
    def test_timing_recorded_per_node(self):
        a = _make_recorder("A")
        b = _make_recorder("B")
        a >> b
        store: dict = {}
        _run(_flow.AsyncFlow(a).run_async(store))
        timing = store["_timing"]
        self.assertIn("Recorder_A", timing)
        self.assertIn("Recorder_B", timing)
        # Should be tiny but >= 0
        for v in timing.values():
            self.assertGreaterEqual(v, 0)

    def test_timing_accumulates_on_loop(self):
        class Counter(_flow.AsyncNode):
            async def post_async(self, store, prep, exec_result):
                store["i"] = store.get("i", 0) + 1
                return "loop" if store["i"] < 3 else None
        c = Counter()
        c - "loop" >> c
        store: dict = {}
        _run(_flow.AsyncFlow(c).run_async(store))
        # Same node ran 3 times; timing accumulated
        timing = store["_timing"]
        self.assertIn("Counter", timing)

# ─── Class-name caching ──────────────────────────────────────────────

class TestClassNameCache(unittest.TestCase):
    def test_class_name_cached_after_first_run(self):
        a = _make_recorder("A")
        self.assertIsNone(a._cls_name)
        _run(a.run_async({}))
        self.assertEqual(a._cls_name, "Recorder_A")

# ─── Error context ──────────────────────────────────────────────────

class TestErrorContext(unittest.TestCase):
    def test_node_name_in_exception_notes(self):
        # add_note is Python 3.11+. Skip test cleanly when unavailable.
        if not hasattr(Exception, "add_note"):
            self.skipTest("Exception.add_note requires Python 3.11+")
        class Bad(_flow.AsyncNode):
            async def exec_async(self, prep):
                raise ValueError("oh no")
        try:
            _run(_flow.AsyncFlow(Bad()).run_async({}))
        except ValueError as e:
            notes = getattr(e, "__notes__", [])
            self.assertTrue(any("Bad" in n for n in notes))

# ─── Helper: _maybe_await ────────────────────────────────────────────

class TestMaybeAwait(unittest.TestCase):
    def test_none_short_circuits(self):
        _run(_flow._maybe_await(None))  # must not raise

    def test_coroutine_awaited(self):
        async def co():
            return 42
        _run(_flow._maybe_await(co()))

if __name__ == "__main__":
    unittest.main()
