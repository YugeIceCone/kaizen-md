#!/usr/bin/env bash
# MIGRATION BRIDGE — health.sh moved to scripts/ops/health.sh in DOMAIN-shells Wave B.
# This stub re-execs the canonical so every legacy caller keeps working.
# Remove once every caller migrates to the canonical path.
_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_DIR="$(cd "$(dirname "$_REAL")" && pwd)"
exec bash "$_DIR/../../../scripts/ops/health.sh" "$@"
