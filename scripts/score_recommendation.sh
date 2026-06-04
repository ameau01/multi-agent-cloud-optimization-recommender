#!/usr/bin/env bash
# Score the agent's recommendation against the gold answer in
# eval-set/expectations/NN/. Reports the four-tier verdict
# (Shape / Correctness / Mid / Rich).
#
# Mid + Rich layers need a judge LLM. If ANTHROPIC_API_KEY or
# OPENAI_API_KEY is set in .env (controlled by LLM_JUDGE_PROVIDER /
# LLM_JUDGE_MODEL), the judge is called once per scoring; otherwise
# Mid + Rich are reported as (skipped) and only Shape + Correctness
# run.
#
# Usage:
#   scripts/score_recommendation.sh <app-NN> [CYCLE_ID] [--no-judge]
#
# Args:
#   app-NN              The application (e.g. app-08). Required.
#   CYCLE_ID            Optional. Defaults to the most recent cycle for app-NN.
#
# Flags:
#   --no-judge          Skip the LLM judge even if a key is set.
#                       Mid and Rich report (skipped).
#   -h, --help          Show this help message and exit.
#
# Examples:
#   scripts/score_recommendation.sh app-08
#   scripts/score_recommendation.sh app-08 --no-judge
#   scripts/score_recommendation.sh app-08 cycle_20260603_111542_23536842

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -e
cd "$(dirname "$0")/.."

APP_NAME="${1:-}"
shift || true

if [[ -z "$APP_NAME" ]]; then
  echo "Usage: scripts/score_recommendation.sh <app-NN> [CYCLE_ID] [--no-judge]" >&2
  exit 2
fi

CYCLE_ID=""
NO_JUDGE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-judge) NO_JUDGE="--no-judge"; shift ;;
    cycle_*) CYCLE_ID="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Write the agent's recommendation as a prediction JSON file to a
# tempfile, then hand it to the existing `python -m src.evaluator.eval`
# CLI (the same one used for scoring uploaded predictions). One
# temp-file lifecycle, one cleanup trap, two stages.

PRED_FILE="$(mktemp -t agent_pred.XXXXXX.json)"
trap 'rm -f "$PRED_FILE"' EXIT

# Stage 1: pull the recommendation from the audit DB and write a
# prediction dict to PRED_FILE.
# Quoted heredoc ('PY') disables bash expansion inside the body so
# backticks in Python comments don't get parsed as command substitution.
# Bash vars get passed as positional args via sys.argv instead.
uv run python - "$APP_NAME" "$CYCLE_ID" "$PRED_FILE" <<'PY'
"""Pull the cycle's recommendation, write prediction JSON to argv[3]."""

import json
import re
import sys

from src.audit.inspect import _resolve_target
from src.audit.queries import get_cycle_events
from src.common.init import get_audit_store

app_name = sys.argv[1]
cycle_id_in = sys.argv[2] or None
pred_path = sys.argv[3]

m = re.match(r"^app-(\d{2})$", app_name)
if not m:
    print(f"ERROR: expected 'app-NN', got {app_name!r}", file=sys.stderr)
    sys.exit(2)
sid = m.group(1)

store = get_audit_store()
cycle_id = _resolve_target(store, app_name, cycle_id_in)

events = get_cycle_events(store, cycle_id)
rec_rows = [e for e in events if e.type == "recommendation"]
if not rec_rows:
    print(
        f"No recommendation row in cycle {cycle_id} (app={app_name}).",
        file=sys.stderr,
    )
    sys.exit(1)

rc = rec_rows[-1].content
composite_in = rc.get("composite") or {}
# Coerce: langchain-anthropic occasionally serializes the nested
# `recommendation` object as a JSON string instead of a dict.
if isinstance(composite_in, str):
    try:
        composite_in = json.loads(composite_in)
    except json.JSONDecodeError:
        composite_in = {}
if not isinstance(composite_in, dict):
    composite_in = {}


def _coerce_optional(value):
    """Coerce a value to a dict, parsing JSON-strings if needed; return
    None for missing or unparseable values so the eval CLI's Optional
    fields stay None rather than getting a malformed sub-object.
    Mirrors render_recommendation.sh's helper of the same name."""
    if value is None:
        return None
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return value if isinstance(value, dict) else None

# Same mapping as render_recommendation.sh -- keep both scripts'
# normalization rule identical so render and score see the same shape.
# Prefer the agent's explicit specific_change field; older cycles
# (pre produce_synthesis schema update) fall back to reasoning then
# headline.
specific_change = (
    composite_in.get("specific_change")
    or composite_in.get("reasoning")
    or composite_in.get("headline")
    or "(agent did not populate a specific_change field)"
)

prediction = {
    "scenario_id":      sid,
    "specific_change":  specific_change,
    "finding_type":     composite_in.get("finding_type"),
    "primary_tier":     composite_in.get("primary_tier"),
    "secondary_tier":   composite_in.get("secondary_tier"),
    "action_category":  composite_in.get("action_category"),
    "headline":         composite_in.get("headline"),
    "reasoning":        composite_in.get("reasoning"),
    # The three structured sub-objects the Rich layer's structural
    # checks read. Pass them through verbatim so the Scorer's
    # evidence_structured / projected_state_quantified /
    # cost_impact_quantified checks can see them. Dropping these here
    # (as the previous version did) made Rich fail even when the agent
    # populated the fields correctly. _coerce_optional handles the
    # langchain-anthropic JSON-string quirk and the absent-field case
    # (restraint/deferral cycles); both showed up as quick crashes in
    # the 18-scenario integration test.
    "evidence":         _coerce_optional(composite_in.get("evidence")),
    "projected_state":  _coerce_optional(composite_in.get("projected_state")),
    "cost_impact":      _coerce_optional(composite_in.get("cost_impact")),
}
# Drop only the OPTIONAL sub-object fields when None. The top-level
# taxonomy fields (finding_type, primary_tier, secondary_tier,
# action_category, headline, reasoning) stay even when null — Shape's
# field_present check requires them to exist as keys, and for
# no_issue_found / diagnostic_deferral the agent legitimately produces
# null primary_tier / action_category. Dropping them made app-06 (a
# correct no_issue_found recommendation) fail Shape on field_present
# while passing Correctness via the short-circuit rule, producing a
# misleading "Shape fail" verdict.
_DROP_IF_NONE = ("evidence", "projected_state", "cost_impact")
for _k in _DROP_IF_NONE:
    if prediction.get(_k) is None:
        prediction.pop(_k, None)

with open(pred_path, "w") as fh:
    json.dump(prediction, fh, indent=2)

print(
    f"Scoring cycle {cycle_id} (app={app_name}) against "
    f"eval-set/expectations/{sid}/raw_recommendation.json...",
    file=sys.stderr,
)
PY

# Stage 2: hand the prediction file to the existing eval CLI.
# We don't `exec` so we can surface the first few error lines on failure
# — the integration test's per-step .score logfile captures full stderr,
# but a tail-N pre-print on exit lets a human running this script
# standalone see the failure root cause without opening the log file.
# Capture eval output to a tempfile, tee it to stdout/stderr live, then
# on non-zero exit re-print the head so the failure is visible in
# whatever wrapped this script (e.g. the integration test's spinner-only
# stdout).
EVAL_OUT="$(mktemp -t score_eval.XXXXXX)"
trap 'rm -f "$PRED_FILE" "$EVAL_OUT"' EXIT

set +e
uv run python -m src.evaluator.eval \
  --app-name "$APP_NAME" \
  --prediction "$PRED_FILE" \
  $NO_JUDGE 2>&1 | tee "$EVAL_OUT"
EVAL_STATUS=${PIPESTATUS[0]}
set -e

if [[ $EVAL_STATUS -ne 0 ]]; then
  echo >&2
  echo "--- score_recommendation FAILED (exit $EVAL_STATUS) ---" >&2
  echo "  app=$APP_NAME cycle=$CYCLE_ID" >&2
  echo "  first error lines from eval CLI:" >&2
  head -10 "$EVAL_OUT" | sed 's/^/    /' >&2
  echo "----------------------------------------------------" >&2
fi
exit "$EVAL_STATUS"
