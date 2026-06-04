#!/usr/bin/env bash
# Show the final recommendation the Cross-Tier Evaluator produced for one
# cycle, plus its drift verdicts, trade-off scores, and the Action
# Harness gate verdict. Lightweight summary view — no full report
# rendering, no eval-set scoring.
#
# Usage:
#   scripts/show_recommendation.sh <app-NN> [CYCLE_ID]
#
# Args:
#   app-NN              The application (e.g. app-08). Required.
#   CYCLE_ID            Optional. Defaults to the most recent cycle for app-NN.
#
# Flags:
#   --json              Dump the full recommendation + evaluator + gate
#                       payloads as JSON instead of the pretty summary.
#   -h, --help          Show this help message and exit.
#
# Examples:
#   scripts/show_recommendation.sh app-08
#   scripts/show_recommendation.sh app-08 cycle_20260603_111542_23536842
#   scripts/show_recommendation.sh app-08 --json

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -e
cd "$(dirname "$0")/.."

APP_NAME="${1:-}"
shift || true

if [[ -z "$APP_NAME" ]]; then
  echo "Usage: scripts/show_recommendation.sh <app-NN> [CYCLE_ID] [--json]" >&2
  echo "  e.g.  scripts/show_recommendation.sh app-08" >&2
  exit 2
fi

CYCLE_ID=""
JSON_MODE="False"   # capitalized so it interpolates as a Python bool below
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_MODE="True"; shift ;;
    cycle_*) CYCLE_ID="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

uv run python - <<PY
"""Pull the recommendation + evaluator + gate-verdict for one cycle and
print a one-screen summary. Reads through the AuditStore so the on-disk
DB at AUDIT_DB_PATH is the source of truth."""

import json
import sys

from src.audit.inspect import _resolve_target
from src.audit.queries import (
    get_cycle_events,
    get_harness_events_for_cycle,
)
from src.common.init import get_audit_store

app_name = "$APP_NAME"
cycle_id = "$CYCLE_ID" or None
json_mode = ${JSON_MODE}

store = get_audit_store()

# Resolve the cycle. Delegates to inspect.py's resolver so this script
# behaves identically to the show_audit_trail / show_orchestration_trace
# wrappers — APP-only means "most recent cycle for that app", and a
# full cycle_id is honoured (with sanity check that it belongs to app).
cycle_id = _resolve_target(store, app_name, cycle_id)

# 2. Pull the audit + harness rows for this cycle.
events = get_cycle_events(store, cycle_id)
h_events = get_harness_events_for_cycle(store, cycle_id)

rec_rows = [e for e in events if e.type == "recommendation"]
ev_rows = [e for e in events if e.type == "evaluator_record"]
gate_rows = [h for h in h_events if h.type == "gate_verdict"]

if not rec_rows:
    print(
        f"No recommendation row in cycle {cycle_id} (app={app_name}). "
        f"The cycle may have terminated before the Evaluator ran "
        f"(restraint, deferral, or failure).",
        file=sys.stderr,
    )
    sys.exit(1)

rec = rec_rows[-1]
ev = ev_rows[-1] if ev_rows else None
gate = gate_rows[-1] if gate_rows else None

# 3. JSON mode short-circuits to a machine-readable dump.
if json_mode:
    payload = {
        "cycle_id": cycle_id,
        "application_id": app_name,
        "recommendation": rec.content,
        "evaluator_record": ev.content if ev else None,
        "gate_verdict": gate.content if gate else None,
    }
    print(json.dumps(payload, indent=2, default=str))
    sys.exit(0)

# 4. Pretty summary. langchain-anthropic sometimes serializes nested
# tool-output objects as JSON strings rather than dicts, so coerce here
# to make older audit rows readable too.
composite = rec.content.get("composite") or {}
if isinstance(composite, str):
    try:
        composite = json.loads(composite)
    except json.JSONDecodeError:
        composite = {}
if not isinstance(composite, dict):
    composite = {}
evidence_refs = rec.content.get("evidence_refs") or []

print(f"=== recommendation  app={app_name}  cycle={cycle_id} ===")
print()
print(f"  finding_type      : {composite.get('finding_type', '-')}")
print(f"  primary_tier      : {composite.get('primary_tier', '-')}")
print(f"  secondary_tier    : {composite.get('secondary_tier', '-')}")
print(f"  action_category   : {composite.get('action_category', '-')}")
print(f"  headline          : {composite.get('headline', '-')}")

specific_change = composite.get("specific_change") or ""
if specific_change:
    print("  specific_change   :")
    for line in specific_change.splitlines() or [specific_change]:
        print(f"    {line}")

reasoning = composite.get("reasoning") or ""
if reasoning:
    print("  reasoning         :")
    for line in reasoning.splitlines() or [reasoning]:
        print(f"    {line}")

if evidence_refs:
    print(f"  evidence_refs     : {evidence_refs}")

# 5. Evaluator-side context.
if ev is not None:
    ec = ev.content
    print()
    print("--- evaluator synthesis ---")
    drift = ec.get("drift_verdicts") or {}
    if drift:
        print("  drift_verdicts    :")
        for specialist, verdict in drift.items():
            print(f"    {specialist:24} {verdict}")
    trade = ec.get("trade_off_scores") or {}
    if trade:
        print("  trade_off_scores  :")
        for axis, score in trade.items():
            print(f"    {axis:24} {score}")
    interactions = ec.get("cross_tier_interactions") or []
    if interactions:
        print(f"  cross_tier_inter. : {len(interactions)} interaction(s)")
    confidence = ec.get("evaluator_confidence")
    if confidence is not None:
        print(f"  evaluator_conf.   : {confidence}")

# 6. Gate verdict from harness_trail.
if gate is not None:
    gc = gate.content
    print()
    print("--- gate verdict ---")
    print(f"  verdict           : {gate.verdict}")
    print(f"  severity          : {gc.get('severity_classification', '-')}")
    print(f"  duplication_check : {gc.get('duplication_check_result', '-')}")
    if gc.get("rejection_reason"):
        print(f"  rejection_reason  : {gc['rejection_reason']}")

print()
PY
