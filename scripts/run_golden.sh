#!/usr/bin/env bash
# Run gold-answer validation tests: every gold answer through the four-layer
# scorer. The headline benchmark-integrity check. If this passes, rules and
# golds are aligned.
#
# Usage:
#   scripts/run_golden.sh [pytest args]

set -e
cd "$(dirname "$0")/.."

uv run python -m pytest tests/integration/test_golden_answers.py "$@"
