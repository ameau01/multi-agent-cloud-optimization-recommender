#!/usr/bin/env bash
# Run all integration tests:
#   - tests/integration/test_eval_set_data.py   (gold answer well-formedness)
#   - tests/integration/test_golden_answers.py  (gold passes evaluator)
#   - tests/integration/test_edge_cases.py      (bad mocks fail expected layer)
#
# Usage:
#   scripts/run_integration.sh [pytest args]

set -e
cd "$(dirname "$0")/.."

uv run python -m pytest tests/integration/ "$@"
