#!/usr/bin/env bash
# kaizen lint_fix — companion setup script (calls Python source of truth).
#
# Usage:
#   bash setup-local-llm.sh                       # ollama (default)
#   bash setup-local-llm.sh --target llama-server # alternative
#
# This is intentionally a tiny wrapper — the bash body of each
# install path lives in lint_fix_setup.py::generate_install_script
# so the Python tests can assert on it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="ollama"

if [[ "${1:-}" == "--target" && -n "${2:-}" ]]; then
  TARGET="$2"
  shift 2
fi

# Generate the per-target install script via the Python source of truth
# and pipe it straight into bash. Keeps a single canonical body.
python3 "$SCRIPT_DIR/lint_fix_setup.py" --print-script --target "$TARGET" | bash
