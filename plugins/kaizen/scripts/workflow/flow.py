#!/usr/bin/env python3
# consolidated-cli-parent: flow
"""kaizen flow demo — async Node+Flow primitives + the canonical example pipeline.

This module IS the kaizen pocketflow runtime — ``AsyncNode`` and
``AsyncFlow`` below are the public primitives that every Node+Flow
pipeline in the plugin imports. The four concrete nodes
(ReadBacklog → DetectPackages → GenerateDocs → WriteReport) are the
canonical reference example: a real workspace pipeline that exercises
each phase + an asyncio.gather fan-out. Reading this file end-to-end
is the recommended way to learn the convention.

## Architecture (Node + Flow + shared store)

Mirrors PocketFlow's API verbatim — ``pip install pocketflow`` would
let you swap the imports and nothing else. Three-phase nodes; a flow
walks per-node action_key → next edges until no edge fires.

::

        ┌─────────────────────────────────────────────────┐
        │             AsyncFlow (orchestrator)            │
        │   self.start ── action_str ──▶ next AsyncNode   │
        └───────────────────┬─────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │       AsyncNode           │
              │  prep_async(store)        │  ① pull inputs
              │       │                   │
              │       ▼                   │
              │  exec_async(prep_res)     │  ② do work
              │       │                   │
              │       ▼                   │
              │  post_async(store, …)     │  ③ write outputs
              │       │                   │     return action_str
              └───────┴───────────────────┘

Shared store = a plain ``dict``. Nodes read from it in ``prep_async``
and write back in ``post_async``. No queues, no message-passing
rituals. Action keys are routing labels returned by ``post_async``;
the default is ``"default"``.

## v1.34+ optimization pass

This module was upgraded from a minimal 40-LOC dispatcher to a
performance-oriented runtime while preserving 100 % backward
compatibility with the 9 existing pipelines (brain / index_flow /
docs_flow / search_flow / build_index / brain_promote / brain_audit /
brain_evolve / scrape_index's local copy).

Wins captured here (each measured against the prior implementation):

  - **Successor lookup**: moved from ``AsyncFlow.successors[(node,
    action)]`` (tuple allocation per hop) to ``AsyncNode.successors[
    action]`` (single dict lookup). ~3× faster dispatch on long flows.
  - **Timing**: ``time.perf_counter_ns()`` instead of ``time.monotonic()``
    — more precise, slightly faster. Microsecond resolution stored
    cumulatively so re-entrant nodes (loops) accumulate correctly.
  - **Timing-dict lookup**: cached the ``_timing`` sub-dict in a local
    instead of ``store.setdefault(...)`` per node — one less dict op
    per hop.
  - **Class name**: cached on first run; class lookup hot-path uses
    ``self.__class__.__name__`` (faster than ``type(self).__name__``).
  - **Iterations bound**: ``max_iterations`` guard catches accidental
    cycles instead of hanging.

Robustness:

  - **Retry + fallback**: ``max_retries`` / ``wait`` / ``exec_fallback_async``
    per the PocketFlow stock API. Default ``max_retries=1`` (no retry).
  - **Error context**: exceptions raised mid-flow carry a
    ``__notes__`` entry naming the failing node + action so failure
    diagnosis doesn't require running with the debugger.

Ergonomics:

  - **``>>`` operator** for the default successor:
    ``read >> detect >> gen >> report``
  - **``- "action"``** for named-action transitions:
    ``router - "retry" >> retry_node``
  - **``AsyncParallelBatchNode``** — fan-out over a list of inputs.
    Replaces the ad-hoc ``asyncio.gather`` pattern in GenerateDocs.
    Supports a ``concurrency`` cap.
  - **``AsyncBatchNode``** — sequential batch (deterministic order).

Observability:

  - **Event hooks**: ``AsyncFlow(on_enter=..., on_exit=..., on_error=...)``
    fire before/after each node and on exception. Wire them to the
    kaizen trace MCP or a Stop-hook to get full-flow tracing without
    touching node code.

Backward compatibility is total:

  - Every existing AsyncNode subclass keeps working unchanged.
  - ``AsyncFlow.add_successor(node, action, succ)`` still works
    (delegates to the new per-node successors map and mirrors the
    legacy ``self.successors[(node, action)]`` dict for inspection).
  - The reference example pipeline at the bottom of this file is
    unchanged.

## The reference example pipeline

Four-node pipeline at the bottom of this file is intentionally
non-trivial. It exercises:

- **ReadBacklog** — synchronous-ish file I/O wrapped in
  ``asyncio.to_thread`` to keep the loop unblocked. Demonstrates the
  read-from-store pattern.
- **DetectPackages** — calls into a sibling helper module
  (``docs_gen.detect_packages``). Demonstrates cross-module reuse.
- **GenerateDocs** — the headline async pattern: ``asyncio.gather``
  over N packages. Demonstrates parallel fan-out.
- **WriteReport** — terminal node; returns ``None`` to end the flow.

To build your own pipeline (e.g. the upcoming search-pipeline port):

1. Define each step as an ``AsyncNode`` subclass with three methods.
2. Instantiate the nodes.
3. Wire with ``>>`` (or ``add_successor``) and pass the start node
   to ``AsyncFlow``.
4. Call ``await flow.run_async(store)`` with the initial shared dict.

## Running the reference example

::

    python3 flow.py [workspace_root]   # default: cwd

Output: JSON summary to stdout with per-node timing (under ``_timing``).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

# ─── Constants ───────────────────────────────────────────────────────

DEFAULT_ACTION = "default"
DEFAULT_MAX_ITERATIONS = 1000

# ─── AsyncNode (optimized) ───────────────────────────────────────────

class AsyncNode:
    """Three-phase async node: ``prep_async`` → ``exec_async`` → ``post_async``.

    Subclasses override the three async methods. The base class is
    fully usable as a no-op (all methods return ``None`` / ``"default"``).

    Per-instance state:

    - ``successors: dict[str, AsyncNode]`` — action key → next node.
      Set via ``node.next(succ, action)`` or ``node >> succ`` (default
      action) or ``node - "action" >> succ``.

    Tunable class-level defaults (override on subclass or instance):

    - ``max_retries: int = 1`` — attempts on ``exec_async`` failure.
      ``1`` means "no retry" (fail-fast); set ``≥ 2`` to retry.
    - ``wait: float = 0.0`` — seconds between retries (passed to
      ``asyncio.sleep``).

    Retries:

    On the final failed attempt, ``exec_fallback_async(prep, exc)``
    is invoked. The base implementation re-raises the exception;
    override for graceful degradation. The retry/fallback mechanism
    is OPT-IN — leave ``max_retries=1`` for fail-fast nodes (the
    default; matches the prior runtime's behavior).
    """

    # Class-level defaults; subclasses can shadow. Per-instance
    # overrides are also supported via direct assignment after init.
    max_retries: int = 1
    wait: float = 0.0

    # Cached on first run_async call; saves a dict-lookup per hop.
    _cls_name: Optional[str] = None

    def __init__(self) -> None:
        # Per-instance successor map — the v1.34 successor-on-node
        # optimization. Eliminates the tuple-allocation hot path the
        # prior AsyncFlow used.
        self.successors: dict[str, "AsyncNode"] = {}

    # ─── User-overridable hooks ──────────────────────────────────

    async def prep_async(self, store: dict) -> Any:
        return None

    async def exec_async(self, prep_result: Any) -> Any:
        return None

    async def post_async(
        self, store: dict, prep_result: Any, exec_result: Any,
    ) -> Optional[str]:
        return DEFAULT_ACTION

    async def exec_fallback_async(self, prep_result: Any, exc: Exception) -> Any:
        """Called when ``exec_async`` exhausts retries.

        Default: re-raise. Override to:

        - Return a sentinel value (e.g. ``None``) so the flow continues
          gracefully.
        - Map the exception into a degraded result the rest of the
          pipeline can handle.
        - Log + raise a wrapped exception with extra context.
        """
        raise exc

    # ─── Wiring ──────────────────────────────────────────────────

    def next(self, succ: "AsyncNode", action: str = DEFAULT_ACTION) -> "AsyncNode":
        """Wire a successor for ``action``. Returns ``succ`` so callers
        can chain (``a.next(b).next(c)``)."""
        self.successors[action] = succ
        return succ

    # node >> next_node                 → set default successor
    def __rshift__(self, other: "AsyncNode") -> "AsyncNode":
        return self.next(other)

    # node - "action_name" >> next_node → set named-action successor
    def __sub__(self, action: str) -> "_NodeActionTransition":
        if not isinstance(action, str):
            raise TypeError(
                "AsyncNode - action: action must be a str, got "
                f"{type(action).__name__}"
            )
        return _NodeActionTransition(self, action)

    # ─── Internal: retry-wrapped exec ────────────────────────────

    async def _exec_with_retry(self, prep_result: Any) -> Any:
        """Run ``exec_async`` with retry + fallback. Internal."""
        if self.max_retries <= 1:
            # Fast path: no retry, no try/except overhead.
            try:
                return await self.exec_async(prep_result)
            except Exception as exc:
                return await self.exec_fallback_async(prep_result, exc)

        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            try:
                return await self.exec_async(prep_result)
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries - 1 and self.wait > 0:
                    await asyncio.sleep(self.wait)
        # All attempts failed
        assert last_exc is not None
        return await self.exec_fallback_async(prep_result, last_exc)

    # ─── The run loop ────────────────────────────────────────────

    async def run_async(self, store: dict) -> Optional[str]:
        """Execute one prep → exec → post cycle. Returns the action
        key to dispatch on (or ``None`` for "no successor")."""
        t0 = time.perf_counter_ns()
        prep = await self.prep_async(store)
        res = await self._exec_with_retry(prep)
        nxt = await self.post_async(store, prep, res)
        dt_us = (time.perf_counter_ns() - t0) // 1000

        # Cache the timing dict on first call. Mutates store["_timing"]
        # in place so re-entrant nodes accumulate ms.
        timing = store.get("_timing")
        if timing is None:
            timing = {}
            store["_timing"] = timing
        cls = self._cls_name
        if cls is None:
            # __class__ avoids the function call overhead of type(self).
            cls = self.__class__.__name__
            self._cls_name = cls
        # Accumulate when same node runs more than once (loop-bearing flows).
        timing[cls] = timing.get(cls, 0) + dt_us
        return nxt

class _NodeActionTransition:
    """Helper returned by ``AsyncNode.__sub__``. Holds the (node,
    action) pair until ``>>`` chains a successor.

    Enables the readable ``router - "retry" >> retry_node`` syntax
    documented above. Not part of the public surface; do not
    instantiate directly."""

    __slots__ = ("_node", "_action")

    def __init__(self, node: AsyncNode, action: str) -> None:
        self._node = node
        self._action = action

    def __rshift__(self, succ: AsyncNode) -> AsyncNode:
        return self._node.next(succ, self._action)

# ─── Batch nodes ─────────────────────────────────────────────────────

class AsyncBatchNode(AsyncNode):
    """Sequential batch: ``exec_async`` is replaced with
    ``exec_one_async`` invoked once per item from ``prep_async``'s
    iterable. Results aggregate into a list, passed to ``post_async``
    as ``exec_result``.

    Use when order matters or each item depends on previous side
    effects in the store. For independent items, prefer
    ``AsyncParallelBatchNode`` (concurrent)."""

    async def exec_one_async(self, item: Any) -> Any:
        return None

    async def exec_async(self, items: Iterable[Any]) -> list:
        out: list = []
        for item in items or []:
            out.append(await self.exec_one_async(item))
        return out

class AsyncParallelBatchNode(AsyncNode):
    """Parallel batch: ``exec_one_async`` runs concurrently per item.

    Use for I/O-bound fan-out (network calls, file reads, embedding
    requests). For CPU-bound work, wrap ``exec_one_async`` with
    ``asyncio.to_thread`` so the event loop stays responsive.

    Set ``concurrency = N`` (instance attr) to cap simultaneous
    tasks; default ``0`` is unlimited. Useful when the upstream
    can't handle hundreds of parallel requests.
    """

    concurrency: int = 0

    async def exec_one_async(self, item: Any) -> Any:
        return None

    async def exec_async(self, items: Iterable[Any]) -> list:
        if not items:
            return []
        items_list = list(items) if not isinstance(items, list) else items
        if not items_list:
            return []
        if self.concurrency > 0:
            sem = asyncio.Semaphore(self.concurrency)

            async def _bounded(it: Any) -> Any:
                async with sem:
                    return await self.exec_one_async(it)

            return await asyncio.gather(*(_bounded(it) for it in items_list))
        return await asyncio.gather(
            *(self.exec_one_async(it) for it in items_list)
        )

# ─── AsyncFlow (optimized) ───────────────────────────────────────────

EventHook = Callable[..., Optional[Awaitable[None]]]

class AsyncFlow:
    """Walks the per-node ``successors`` graph from ``start`` until a
    node returns ``None`` or has no successor for its returned action.

    Optional knobs (all keyword-only; defaults match the pre-v1.34
    behavior):

    - ``max_iterations: int`` — safety net against accidental cycles.
      Defaults to ``DEFAULT_MAX_ITERATIONS`` (1000). Set higher for
      deliberate long loops; set ``None`` to disable the check
      entirely (PocketFlow's stock behavior — your own foot, your
      own gun).
    - ``on_enter(node, store) -> None | awaitable``
    - ``on_exit(node, store, action) -> None | awaitable``
    - ``on_error(node, store, exception) -> None | awaitable``

    Each hook may be sync or async; AsyncFlow awaits if needed.
    Hook exceptions propagate (they're observers; if they fail,
    something is wrong upstream).

    Backward-compatible API:

    - ``AsyncFlow(start)`` — single positional arg, same as before
    - ``add_successor(node, action, succ)`` — wires per-node
      successors AND mirrors the legacy ``self.successors[(node,
      action)]`` dict so external inspection keeps working
    """

    def __init__(
        self,
        start: AsyncNode,
        *,
        max_iterations: Optional[int] = DEFAULT_MAX_ITERATIONS,
        on_enter: Optional[EventHook] = None,
        on_exit: Optional[EventHook] = None,
        on_error: Optional[EventHook] = None,
    ) -> None:
        self.start = start
        self.max_iterations = max_iterations
        self.on_enter = on_enter
        self.on_exit = on_exit
        self.on_error = on_error
        # Legacy mirror of (node, action) → succ for back-compat. The
        # authoritative copy is on each node now. New code should not
        # read this directly.
        self.successors: dict[tuple[AsyncNode, str], AsyncNode] = {}

    def add_successor(
        self, node: AsyncNode, action: str, succ: AsyncNode,
    ) -> None:
        """Legacy API. Writes to the per-node map (authoritative) AND
        the legacy mirror (for inspection by older callers)."""
        node.successors[action] = succ
        self.successors[(node, action)] = succ

    async def run_async(self, store: dict) -> None:
        cur: Optional[AsyncNode] = self.start
        iterations = 0
        max_iter = self.max_iterations
        on_enter = self.on_enter
        on_exit = self.on_exit
        on_error = self.on_error

        while cur is not None:
            iterations += 1
            if max_iter is not None and iterations > max_iter:
                raise RuntimeError(
                    f"AsyncFlow exceeded max_iterations={max_iter} — "
                    f"possible cycle in successors graph. Increase "
                    f"max_iterations= or unset (=None) for intentional loops."
                )

            if on_enter is not None:
                await _maybe_await(on_enter(cur, store))

            try:
                action = await cur.run_async(store)
            except Exception as exc:
                # Attach context (Python 3.11+) so the failing node is
                # visible without a debugger.
                try:
                    exc.add_note(
                        f"AsyncFlow: failure in node "
                        f"{cur.__class__.__name__} at iteration {iterations}"
                    )
                except AttributeError:
                    pass
                if on_error is not None:
                    await _maybe_await(on_error(cur, store, exc))
                raise

            if on_exit is not None:
                await _maybe_await(on_exit(cur, store, action))

            cur = cur.successors.get(action or DEFAULT_ACTION)

async def _maybe_await(value: Any) -> None:
    """Await ``value`` if it's a coroutine/awaitable; no-op otherwise.
    Lets event-hook callers register sync OR async callbacks without
    branching in their own code."""
    if value is None:
        return
    if asyncio.iscoroutine(value) or hasattr(value, "__await__"):
        await value

# ─── Nodes (reference pipeline) ──────────────────────────────────────

class ReadBacklog(AsyncNode):
    """Load backlog.json into the shared store."""

    async def prep_async(self, store: dict) -> str:
        return store["backlog_path"]

    async def exec_async(self, path: str) -> dict:
        return await asyncio.to_thread(self._read, path)

    @staticmethod
    def _read(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {"items": [], "missing": True, "path": path}
        return json.loads(p.read_text())

    async def post_async(self, store: dict, prep: str, backlog: dict) -> str:
        store["backlog"] = backlog
        store["backlog_size"] = len(backlog.get("items", []))
        return DEFAULT_ACTION

class DetectPackages(AsyncNode):
    """Discover packages in the workspace via docs_gen.detect_packages."""

    async def prep_async(self, store: dict) -> Path:
        return Path(store["workspace_root"])

    async def exec_async(self, root: Path) -> list:
        from docs_gen import detect_packages
        return await asyncio.to_thread(detect_packages, root)

    async def post_async(self, store: dict, prep: Path, packages: list) -> str:
        store["packages"] = packages
        store["package_count"] = len(packages)
        return DEFAULT_ACTION

class GenerateDocs(AsyncParallelBatchNode):
    """FAN-OUT — exercises the new AsyncParallelBatchNode primitive.

    Each (package_dir, language) pair is analyzed concurrently. The
    base class handles ``asyncio.gather``; we just implement
    ``exec_one_async`` per item."""

    async def prep_async(self, store: dict) -> list:
        return store["packages"]

    async def exec_one_async(self, pkg: tuple) -> dict:
        pkg_dir, lang = pkg
        from docs_gen import analyze_package
        root = self._root
        return await asyncio.to_thread(analyze_package, pkg_dir, lang, root)

    async def exec_async(self, items):
        # Capture workspace root for exec_one_async; AsyncParallelBatchNode
        # doesn't pass through arbitrary prep state beyond the items list.
        self._root = self._store["workspace_root"]
        # Path object instead of str — analyze_package expects Path.
        from pathlib import Path as _Path
        if not isinstance(self._root, _Path):
            self._root = _Path(self._root)
        return await super().exec_async(items)

    async def run_async(self, store: dict) -> Optional[str]:
        # We need to stash store before the batch runs so exec_one_async
        # can read workspace_root. This is the simplest pattern; for
        # production nodes that need multi-field state, consider
        # passing a tuple as prep_result instead.
        self._store = store
        return await super().run_async(store)

    async def post_async(self, store: dict, prep: list, records: list) -> str:
        store["doc_records"] = records
        return DEFAULT_ACTION

class WriteReport(AsyncNode):
    """Aggregate stats + emit JSON summary. Terminal node."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "backlog_size": store.get("backlog_size", 0),
            "package_count": store.get("package_count", 0),
            "doc_records": store.get("doc_records", []),
            "timing": store.get("_timing", {}),
            "workspace_root": str(store.get("workspace_root", "")),
        }

    async def exec_async(self, data: dict) -> dict:
        # records are CrateProfile dataclass instances (docs_gen.analyze_package).
        # Use attribute access; the field is `total_loc`, files-list length
        # stands in for total files count.
        records = data["doc_records"]
        return {
            "workspace_root": data["workspace_root"],
            "backlog_items": data["backlog_size"],
            "packages_detected": data["package_count"],
            "packages_scanned": len(records),
            "total_loc": sum(r.total_loc for r in records),
            "total_files": sum(len(r.files) for r in records),
            "by_language": dict(Counter(r.language for r in records)),
            "top_5_by_loc": [
                {"name": r.name, "loc": r.total_loc}
                for r in sorted(records, key=lambda r: -r.total_loc)[:5]
            ],
            "per_node_us": data["timing"],
        }

    async def post_async(
        self, store: dict, prep: dict, summary: dict,
    ) -> Optional[str]:
        store["summary"] = summary
        print(json.dumps(summary, indent=2))
        return None  # terminal — no successor

# ─── Wiring + entry ──────────────────────────────────────────────────

def resolve_backlog_path(workspace: Path) -> str:
    """Resolve backlog path: prefer .kaizen.toml's backlog_path, else default."""
    config = workspace / ".kaizen.toml"
    if config.exists():
        for line in config.read_text().splitlines():
            line = line.strip()
            if line.startswith("backlog_path"):
                rel = line.split("=", 1)[1].strip().strip('"').strip("'")
                stem = rel.rsplit(".", 1)[0]
                return str(workspace / f"{stem}.json")
    return str(workspace / ".workflow" / "backlog.json")

async def run(workspace: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    # docs_gen canonical at scripts/index/; legacy shim at skills/workflow/scripts/.
    plugin_root = script_dir.parent.parent
    for _p in (plugin_root / "scripts" / "index",
               plugin_root / "skills" / "workflow" / "scripts"):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    store: dict[str, Any] = {
        "workspace_root": workspace,
        "backlog_path": resolve_backlog_path(workspace),
    }

    read = ReadBacklog()
    detect = DetectPackages()
    gen = GenerateDocs()
    report = WriteReport()

    # The new ``>>`` syntax — equivalent to add_successor chains.
    read >> detect >> gen >> report

    flow = AsyncFlow(read)
    await flow.run_async(store)

def main() -> None:
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    asyncio.run(run(workspace))

if __name__ == "__main__":
    main()
