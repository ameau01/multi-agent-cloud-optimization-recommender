#!/usr/bin/env bash
# Run one cycle of the agent system on an app-name.
#
# Usage:
#   scripts/run_agents.sh <app-NN> [--trigger manual|scheduled|test]
#
# Args:
#   app-NN              The application to review (e.g. app-08).
#
# Flags:
#   --trigger TYPE      Trigger label recorded on the cycle (default: manual).
#   -h, --help          Show this help message and exit.
#
# Example:
#   scripts/run_agents.sh app-08
#   scripts/run_agents.sh app-08 --trigger scheduled

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -e
cd "$(dirname "$0")/.."

APP_NAME="${1:-}"
shift || true

if [[ -z "$APP_NAME" ]]; then
  echo "Usage: scripts/run_agents.sh <app-NN> [--trigger manual|scheduled|test]" >&2
  echo "  e.g.  scripts/run_agents.sh app-08" >&2
  exit 2
fi

TRIGGER_TYPE="manual"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --trigger)
      TRIGGER_TYPE="$2"
      shift 2
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
  esac
done

# Run the agent cycle via a one-liner Python invocation. The runner lives at
# src/agents/runner.py; uv ensures the venv has every dependency.
#
# We background the Python process so the foreground shell can paint a
# spinner + elapsed-seconds counter — the cycle takes ~60s end-to-end
# (System Mapper + two specialists doing ReAct loops + Evaluator), and
# silent waits are unfriendly. Output is captured to a tempfile and
# printed after the spinner clears so the spinner doesn't interleave
# with cycle_id / next-steps output.

LOG="$(mktemp -t agent_cycle.XXXXXX)"
trap 'rm -f "$LOG"' EXIT

printf "Running agent cycle for %s (trigger=%s)...\n" "$APP_NAME" "$TRIGGER_TYPE"
START=$(date +%s)

uv run python - <<PY >"$LOG" 2>&1 &
from src.agents.runner import run_cycle, langsmith_enabled

cycle_id = run_cycle("$APP_NAME", trigger_type="$TRIGGER_TYPE")
print(f"cycle_id = {cycle_id}")
print(f"langsmith_enabled = {langsmith_enabled()}")
print()
print("Next steps:")
print()
print("  # Recommendation + scoring (start here):")
print(f"  scripts/show_recommendation.sh $APP_NAME            # one-screen summary of the synthesis")
print(f"  scripts/render_recommendation.sh $APP_NAME          # render as markdown report")
print(f"  scripts/score_recommendation.sh $APP_NAME           # 4-tier score vs gold answer")
print()
print("  # Full trail (when you need the audit-level detail):")
print(f"  scripts/show_audit_trail.sh $APP_NAME")
print(f"  scripts/show_orchestration_trace.sh $APP_NAME --type decisions")
print(f"  scripts/show_orchestration_trace.sh $APP_NAME --type evidence")
print(f"  scripts/show_orchestration_trace.sh $APP_NAME {cycle_id} --type decisions,evidence  # pin this exact cycle")
PY
PID=$!

# Spinner. \r returns the cursor to column 0 so we overwrite the same
# line each tick. Trailing spaces clear residue from longer prior frames.
SPIN='|/-\'
i=0
while kill -0 "$PID" 2>/dev/null; do
  ELAPSED=$(( $(date +%s) - START ))
  printf "\r  %s  working... %ds elapsed   " "${SPIN:i++%${#SPIN}:1}" "$ELAPSED"
  sleep 0.4
done
ELAPSED=$(( $(date +%s) - START ))

# Capture exit status without letting set -e nuke us before we cat the log.
set +e
wait "$PID"
STATUS=$?
set -e

printf "\r  done in %ds                  \n\n" "$ELAPSED"
cat "$LOG"
exit "$STATUS"
