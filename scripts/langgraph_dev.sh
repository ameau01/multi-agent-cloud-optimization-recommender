#!/usr/bin/env bash
# Launch LangGraph dev with the flags this project needs.
#
# Two project-specific flags are wrapped here:
#
#   --allow-blocking
#     The audit store uses sync sqlite3 + SQLAlchemy. LangGraph dev's
#     blockbuster middleware flags every sync DB call as a violation
#     of its async-loop hygiene rules. Switching to aiosqlite is a
#     larger refactor; for a single-user dev session the warning is
#     noise. This flag opts out.
#
#   REPLAY_FIXTURE (env)
#     The `agent_replay` graph reads its canned LLM / MCP responses
#     from a JSON fixture exported via scripts/export_cycle_fixture.py.
#     The default points at the app-08 fixture; override on the
#     command line for any other cycle:
#       REPLAY_FIXTURE=path/to/other.json bash scripts/langgraph_dev.sh
#
# Usage:
#   bash scripts/langgraph_dev.sh             # default fixture (app-08)
#   bash scripts/langgraph_dev.sh --help      # forwarded to langgraph dev
#
# When the server boots it prints a Studio URL like:
#   https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
# Click that to open Studio; the baseUrl parameter is what connects
# the cloud UI back to your local dev server.

set -euo pipefail

DEFAULT_FIXTURE="tests/integration/agents/fixtures/cycle_app08.json"
export REPLAY_FIXTURE="${REPLAY_FIXTURE:-$DEFAULT_FIXTURE}"

if [[ ! -f "$REPLAY_FIXTURE" ]]; then
  echo "error: REPLAY_FIXTURE not found at $REPLAY_FIXTURE" >&2
  echo "" >&2
  echo "Generate one with:" >&2
  echo "  python scripts/export_cycle_fixture.py --cycle <cycle_id> --out $REPLAY_FIXTURE" >&2
  exit 1
fi

echo "Using replay fixture: $REPLAY_FIXTURE"
exec uv run langgraph dev --allow-blocking "$@"
