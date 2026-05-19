#!/usr/bin/env bash
# MIGRATION BRIDGE — disable-skill.sh moved to scripts/install/disable-skill.sh in DOMAIN-shells Wave C.
# This stub re-execs the canonical so every legacy caller keeps working.
# Remove once every caller migrates to the canonical path.
_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_DIR="$(cd "$(dirname "$_REAL")" && pwd)"
exec bash "$_DIR/../../../scripts/install/disable-skill.sh" "$@"
