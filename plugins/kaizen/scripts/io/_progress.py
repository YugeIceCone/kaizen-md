"""Tiny stderr progress reporter for kaizen indexers.

Emits one line per .tick() call. Renders nicely in both a TTY and a pipe:

- **TTY** (running directly from a terminal): overwrites the same line with
  `\\r`, padded to the terminal width — looks like a single live progress
  bar.
- **pipe** (running from `enable_all.sh` / slash command / CI / `tee`):
  prints a fresh line at most once per `every_pct`% milestone so the
  captured output stays compact and human-readable.

Always flushes stderr after every write so progress shows up live.
Stdlib only — no tqdm dep, no PEP 723 metadata change.

Usage:

    from _progress import Progress
    bar = Progress("onboard", total=len(files))
    for f in files:
        process(f)
        bar.tick(msg=f.name)
    bar.done()
"""
from __future__ import annotations

import shutil
import sys
import time

class Progress:
    def __init__(
        self,
        label: str,
        total: int,
        *,
        every_pct: int = 5,
        stream=None,
    ) -> None:
        self.label = label
        self.total = max(total, 0)
        self.n = 0
        self.start = time.monotonic()
        self.stream = stream if stream is not None else sys.stderr
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.every_pct = max(1, min(50, every_pct))
        self._last_emitted_pct = -1

    def tick(self, msg: str = "") -> None:
        self.n += 1
        pct = (self.n * 100 // self.total) if self.total else 100
        # In a pipe, throttle: only emit when we cross a new every_pct% milestone,
        # or on the very last tick.
        if not self.is_tty:
            if pct < self._last_emitted_pct + self.every_pct and self.n != self.total:
                return
            self._last_emitted_pct = pct
        self._write_line(pct, msg)

    def _write_line(self, pct: int, msg: str) -> None:
        elapsed = time.monotonic() - self.start
        if self.total:
            rate = self.n / elapsed if elapsed > 0 else 0.0
            remaining = (self.total - self.n) / rate if rate > 0 else 0.0
            eta = f" eta {remaining:4.0f}s" if self.n < self.total else " done"
            head = f"[{self.label}] {self.n:>5}/{self.total} ({pct:3d}%){eta}"
        else:
            head = f"[{self.label}] {self.n:>5}"
        line = f"{head}  {msg}" if msg else head
        if self.is_tty:
            width = shutil.get_terminal_size((100, 20)).columns
            self.stream.write("\r" + line[: width - 1].ljust(width - 1))
        else:
            self.stream.write(line + "\n")
        try:
            self.stream.flush()
        except Exception:
            pass

    def done(self, summary: str = "") -> None:
        if self.is_tty:
            # Finalise the rewriting line with a newline.
            self.stream.write("\n")
        if summary:
            self.stream.write(f"[{self.label}] {summary}\n")
        try:
            self.stream.flush()
        except Exception:
            pass

# ─── Smoke test / demo ───────────────────────────────────────────────

def _smoke_test() -> None:
    """`python3 _progress.py` — runs a tiny demo + asserts core behaviour.

    Exercises both code paths:
      - TTY: \\r-overwrite (visible if you run interactively)
      - pipe: throttled milestone lines (visible in CI / log capture)
    """
    import io
    import time

    # 1. Pipe-mode throttling: 100-item bar with every_pct=10 should
    #    emit at most ~10 lines, not 100.
    buf = io.StringIO()
    bar = Progress("smoke", total=100, every_pct=10, stream=buf)
    for i in range(100):
        bar.tick(f"item-{i}")
    bar.done("100/100 ok")
    lines = buf.getvalue().splitlines()
    assert len(lines) <= 12, f"pipe mode should throttle (got {len(lines)} lines)"
    assert lines[-1].endswith("100/100 ok"), f"missing summary: {lines[-1]!r}"

    # 2. Tiny totals don't divide by zero.
    buf = io.StringIO()
    bar = Progress("tiny", total=1, stream=buf)
    bar.tick("only one")
    bar.done()
    assert "1/1" in buf.getvalue()

    # 3. Zero total degrades gracefully.
    buf = io.StringIO()
    bar = Progress("empty", total=0, stream=buf)
    bar.done("no work")
    assert "no work" in buf.getvalue()

    # 4. Live demo — only if stderr is a TTY.
    if sys.stderr.isatty():
        sys.stderr.write("\n[demo] live TTY progress (you should see overwriting):\n")
        bar = Progress("demo", total=50)
        for i in range(50):
            bar.tick(f"step-{i}")
            time.sleep(0.02)
        bar.done("done")

    print("✓ _progress.py smoke test pass (3 / 3)")

if __name__ == "__main__":
    _smoke_test()
