#!/usr/bin/env bash
# Walk every sample-run audit trail backward and confirm every parent
# reference resolves. Exits 0 if every reference resolves; non-zero if
# any pointer is dangling in any trace.
#
# Usage:
#   scripts/verify_trace.sh

set -e
cd "$(dirname "$0")/.."

uv run python tests/verify_trace.py "$@"
