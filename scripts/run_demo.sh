#!/usr/bin/env bash
# Run the eval-set demo: score app-08's gold answer through the four-layer
# evaluator and print the per-layer verdict.
#
# Usage:
#   scripts/run_demo.sh                   # Shape + Correctness only (no API key)
#   scripts/run_demo.sh --with-judge      # adds Mid + Rich via the LLM judge
#                                         #   (requires OPENAI_API_KEY or
#                                         #    ANTHROPIC_API_KEY in .env)
#
# Any flags passed are forwarded to eval-set/demo_scoring.py as-is.

set -e
cd "$(dirname "$0")/.."

uv run python eval-set/demo_scoring.py "$@"
