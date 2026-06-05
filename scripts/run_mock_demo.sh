#!/usr/bin/env bash
# Hermetic demo — replay the app-08 cycle from a vendored fixture,
# render the report + trace, no live LLM, no Hugging Face, no API key.
#
# This is what the Docker container (`docker compose up demo`) runs.
# Outputs land in --out-dir (default: ./demo-output/).
#
# Three stages:
#   1. Run the replay graph (tests/run_replay.py) → writes the recorded
#      audit records to a fresh AUDIT_DB_PATH and prints the cycle_id.
#   2. Render report.md from those records with the MOCK MODE banner
#      (scripts/render_recommendation.sh app-08 --mock-mode --out ...).
#   3. Render trace.json and trace.md (scripts/render_evidence_trace.sh).
#
# Usage:
#   scripts/run_mock_demo.sh                       # default: demo-output/
#   scripts/run_mock_demo.sh --out-dir /out        # for the container
#
# Flags:
#   --out-dir DIR   Where to write report.md / trace.json / trace.md.
#                   Default: ./demo-output/
#   --app APP-NN    Application id to replay. Default: app-08
#                   (the only fixture vendored today).
#   --fixture PATH  Cycle-export fixture JSON. Default:
#                   tests/integration/agents/fixtures/cycle_app08.json
#   -h, --help      Show this help message and exit.

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -e
cd "$(dirname "$0")/.."

OUT_DIR="./demo-output"
APP="app-08"
FIXTURE="tests/integration/agents/fixtures/cycle_app08.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --app)     APP="$2"; shift 2 ;;
    --fixture) FIXTURE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT_DIR"

# Force a fresh, isolated audit DB just for this demo. Cleared on every
# run so a stale cycle from a previous demo can't bleed into this one.
DEMO_DB="$OUT_DIR/.demo_audit.db"
rm -f "$DEMO_DB"
export AUDIT_DB_PATH="$DEMO_DB"

echo "================================================================"
echo " Mock-mode demo"
echo "   app       : $APP"
echo "   fixture   : $FIXTURE"
echo "   out_dir   : $OUT_DIR"
echo "   audit_db  : $DEMO_DB"
echo "================================================================"

# ----------------------------------------------------------------------
# Stage 1: replay
# ----------------------------------------------------------------------
echo
echo "--- Stage 1: replay the recorded cycle ---"
CYCLE_ID="$(uv run python tests/run_replay.py \
    --fixture "$FIXTURE" --app "$APP")"
echo "cycle_id=$CYCLE_ID"

# ----------------------------------------------------------------------
# Stage 2: render report (with MOCK MODE banner)
# ----------------------------------------------------------------------
echo
echo "--- Stage 2: render report.md ---"
bash scripts/render_recommendation.sh "$APP" "$CYCLE_ID" \
    --mock-mode --out "$OUT_DIR/report.md"

# ----------------------------------------------------------------------
# Stage 3: render trace.json + trace.md
# ----------------------------------------------------------------------
echo
echo "--- Stage 3: render trace.json + trace.md ---"
bash scripts/render_evidence_trace.sh "$APP" "$CYCLE_ID" \
    --format json --out "$OUT_DIR/trace.json"
bash scripts/render_evidence_trace.sh "$APP" "$CYCLE_ID" \
    --format markdown --out "$OUT_DIR/trace.md"

echo
echo "================================================================"
echo " Done."
echo "   Open these to read the demo output:"
echo "     $OUT_DIR/report.md     (human-readable recommendation)"
echo "     $OUT_DIR/trace.md      (human-readable audit trail)"
echo "     $OUT_DIR/trace.json    (machine-readable audit trail)"
echo "================================================================"
