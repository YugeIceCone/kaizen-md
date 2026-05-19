"""kaizen JSONL helpers — shared read utilities for event-log style files.

Used by trace_index, observe, and any consumer that needs to iterate
JSON-per-line files, optionally gzip-compressed (rotated event logs).

Single source of `iter_jsonl` extracted in the M4 hygiene pass (was
duplicated byte-identical in trace_index.py + observe.py).

## API

    from _jsonl import iter_jsonl

    for record in iter_jsonl(Path("events.jsonl")):
        ...

Generator: yields one parsed dict per non-empty line. Skips invalid
JSON, OSError on the file open. Returns silently if the file doesn't
exist (common when an indexer hits a not-yet-rotated path).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Iterator


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield each JSON record from a .jsonl or .jsonl.gz file.

    Silent on: missing file, OSError, JSONDecodeError per-line, empty lines.
    Use this when you don't want a malformed line to abort the whole pass."""
    if not path.exists():
        return
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return
