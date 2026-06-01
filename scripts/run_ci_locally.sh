#!/usr/bin/env bash
# Run the same checks GitHub Actions runs, locally and in the same order.
# This is the pre-push gate: if this script passes, the workflow_dispatch
# CI run on GitHub will pass too.
#
# Mirrors .github/workflows/ci.yml exactly:
#   1. ruff check     (linting)
#   2. mypy src       (type checking)
#   3. pytest -q      (full test suite, output to stdout)
#
# Stops at the first failure (set -e) so you fix one thing at a time.
# Each step prints a clear banner so the failing step is obvious in the
# scrollback.
#
# Usage:
#   scripts/run_ci_locally.sh
#
# Tip: run this before every git push to GitHub. If it passes here, it
# will pass in CI.

set -e
cd "$(dirname "$0")/.."

banner() {
  echo
  echo "============================================================"
  echo "  $1"
  echo "============================================================"
}

banner "1/3  Linting (ruff check .)"
uv run ruff check .

banner "2/3  Type checking (mypy src)"
uv run mypy src

banner "3/3  Tests (pytest -q)"
uv run python -m pytest -q

banner "All CI checks passed locally. Safe to push."
