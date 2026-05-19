#!/usr/bin/env bash
# MIGRATION BRIDGE — migrate.sh moved to scripts/migrate/migrate.sh in DOMAIN-17.
_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_DIR="$(cd "$(dirname "$_REAL")" && pwd)"
exec bash "$_DIR/../../../scripts/migrate/migrate.sh" "$@"
