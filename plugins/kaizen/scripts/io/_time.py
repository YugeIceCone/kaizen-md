"""kaizen time helpers — single source for UTC now + ISO-8601 formatting.

Consolidates 10 near-identical `now()` / `_now()` / `now_iso()` /
`_now_iso()` helpers scattered across the scripts dir (M5 hygiene).

## API

    from _time import utc_now, iso

    dt_obj = utc_now()                              # datetime, tz-aware UTC
    print(iso())                                    # default ms precision
    print(iso(precision="seconds"))                 # 2026-05-13T22:30:00Z
    print(iso(at=dt.datetime.now(...)))             # format an existing dt

Precision values:
  - "milliseconds" (default) — matches trace_index, observe, trace
  - "seconds"               — matches _blobs, claude_docs_index, docs_gen
  - "microseconds"          — passes through datetime's isoformat default

All outputs are UTC and end with `Z` (not `+00:00`)."""
from __future__ import annotations

import datetime as dt
from typing import Literal

Precision = Literal["seconds", "milliseconds", "microseconds"]

def utc_now() -> dt.datetime:
    """Return a tz-aware UTC `datetime`. Identical to `dt.datetime.now(dt.timezone.utc)`."""
    return dt.datetime.now(dt.timezone.utc)

def iso(at: dt.datetime | None = None, *, precision: Precision = "milliseconds") -> str:
    """Format a `datetime` (default: now) as a Z-terminated ISO-8601 string."""
    when = at if at is not None else utc_now()
    return when.isoformat(timespec=precision).replace("+00:00", "Z")
