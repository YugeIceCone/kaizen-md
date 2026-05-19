#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
# ]
# ///
"""kaizen trace-index GPU variant — uv resolves default-PyPI torch
(includes CUDA wheels on Linux). Use this when you have an NVIDIA GPU
and want GPU acceleration; otherwise use `trace_index.py` (CPU default).

Body delegates to `trace_index.py` via `runpy` — no code duplication.
The active uv env (this script's GPU one) provides torch with CUDA;
trace_index.py's body imports sentence-transformers + torch and uses
whichever env loaded it.

Toggle via env var: `KAIZEN_TRACE_GPU=1 kaizen-trace-index ...` (wrapper
picks this script).
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

# Delegate to trace_index.py within the GPU-resolved uv env.
target = Path(__file__).resolve().parent / "trace_index.py"
if not target.exists():
    sys.stderr.write(f"trace_index_gpu: target {target} not found\n")
    sys.exit(1)

# run_name="__main__" makes argparse fire as if trace_index.py was called directly.
runpy.run_path(str(target), run_name="__main__")
