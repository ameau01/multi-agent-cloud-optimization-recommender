#!/usr/bin/env bash
# Run the full pytest suite (unit + integration). Single entry point for
# "is everything still passing?" — used both locally and as part of the
# pre-push CI script.
#
# Auto-skips tests that need Hugging Face network access when offline
# (the wire-layer MCP test detects this and marks the suite skipped).
#
# Usage:
#   scripts/run_pytest.sh                    # default: verbose, full sweep
#   scripts/run_pytest.sh -x                 # stop at first failure
#   scripts/run_pytest.sh -k composite       # run only matching tests
#   scripts/run_pytest.sh tests/unit/        # just unit tests
#
# Any pytest flags after the script name are passed through.

set -e
cd "$(dirname "$0")/.."

uv run python -m pytest -q "$@"
