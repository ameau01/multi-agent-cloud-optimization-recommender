#!/usr/bin/env bash
# Run a full integration test across all 18 scenarios in four sequential
# steps. Designed to run unattended (~40-50 minutes total) and produce a
# self-contained results directory you can inspect afterwards.
#
# Output directory layout (created in the project root):
#   integration-test-YYYYMMDD_HHMMSS/
#     00_summary.txt             aggregate verdict + timings
#     step1_run_agents/
#       app-NN.log               full run_agents.sh output per scenario
#       cycle_ids.txt            app -> cycle_id map
#     step2_scoring/
#       app-NN.score             score_recommendation.sh output
#       aggregate.txt            pass/fail table (Shape/Correctness/Mid/Rich)
#     step3_evidence_chain/
#       app-NN.verify            verify_evidence_chain.sh output
#       aggregate.txt            resolved/dangling counts per scenario
#     step4_reports/
#       app-NN/
#         report.md              human report
#         trace.md               structured-markdown evidence trace
#         trace.json             machine-readable evidence trace
#
# The script does NOT abort on per-scenario failures — each failure is
# captured to its log file and the aggregate continues. The final
# summary names which scenarios passed each step.
#
# Usage:
#   scripts/integration_test_all.sh [--keep-audit] [--scenarios LIST] [--skip-to N]
#
# Flags:
#   --keep-audit         Skip the initial clean.sh --audit. Preserves any
#                        existing cycles in the audit DB. Default behaviour
#                        is to clean before step 1 for a true fresh run.
#   --scenarios LIST     Comma-separated app-NN list. Default is all 18.
#                        e.g. --scenarios "app-02,app-07,app-08"
#   --skip-to N          Skip steps 1..(N-1) and start at step N. Requires
#                        --keep-audit so the prior step's cycles in the
#                        audit DB are preserved. Useful when step 1 has
#                        already run (~36 min) and you only want to
#                        re-execute scoring/verify/render against the
#                        existing cycles after fixing a downstream bug.
#                        Examples:
#                          --skip-to 2  start at scoring
#                          --skip-to 4  start at report rendering
#   -h, --help           Show this help and exit.

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,38p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -u
cd "$(dirname "$0")/.."

# ----------------------------------------------------------------------
# Arg parsing
# ----------------------------------------------------------------------
KEEP_AUDIT=0
SCENARIO_LIST=""
SKIP_TO=1   # start at step 1 by default; bumped via --skip-to N

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-audit) KEEP_AUDIT=1; shift ;;
    --scenarios)  SCENARIO_LIST="$2"; shift 2 ;;
    --skip-to)    SKIP_TO="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# --skip-to N validation. Must be 1..4 (the four step indices).
if ! [[ "$SKIP_TO" =~ ^[1-4]$ ]]; then
  echo "ERROR: --skip-to must be 1, 2, 3, or 4 (got: $SKIP_TO)" >&2
  exit 2
fi

# Skipping a step implies preserving the prior step's output in the
# audit DB. If the user said --skip-to 2 but did NOT pass --keep-audit,
# the initial clean.sh would wipe the cycles step 2 needs to read.
if [[ "$SKIP_TO" -gt 1 && $KEEP_AUDIT -eq 0 ]]; then
  echo "ERROR: --skip-to $SKIP_TO requires --keep-audit (otherwise the" >&2
  echo "       initial clean.sh would wipe the cycles step ${SKIP_TO} needs" >&2
  echo "       to read). Re-run with both flags:" >&2
  echo "         scripts/integration_test_all.sh --keep-audit --skip-to $SKIP_TO" >&2
  exit 2
fi

# Default scenario list: app-01 through app-18.
if [[ -z "$SCENARIO_LIST" ]]; then
  SCENARIOS=()
  for n in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18; do
    SCENARIOS+=("app-$n")
  done
else
  IFS=',' read -ra SCENARIOS <<< "$SCENARIO_LIST"
fi

TOTAL=${#SCENARIOS[@]}

# ----------------------------------------------------------------------
# Setup workdir + global summary file
# ----------------------------------------------------------------------
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WORKDIR="integration-test-${TIMESTAMP}"
mkdir -p "$WORKDIR/step1_run_agents"
mkdir -p "$WORKDIR/step2_scoring"
mkdir -p "$WORKDIR/step3_evidence_chain"
mkdir -p "$WORKDIR/step4_reports"

SUMMARY="$WORKDIR/00_summary.txt"
RUN_START=$(date +%s)

{
  echo "=== Integration test summary ==="
  echo "Started     : $(date -Iseconds)"
  echo "Scenarios   : $TOTAL ($(IFS=,; echo "${SCENARIOS[*]}"))"
  echo "Workdir     : $WORKDIR"
  echo "Keep audit  : $KEEP_AUDIT"
  echo
} > "$SUMMARY"

echo "============================================================"
echo "Integration test starting"
echo "  workdir   : $WORKDIR"
echo "  scenarios : $TOTAL"
echo "  estimate  : ~$((TOTAL * 130 / 60)) min for step 1 + ~5 min for steps 2-4"
echo "============================================================"
echo

# ----------------------------------------------------------------------
# Helper: run a command with a spinner + elapsed-seconds counter.
# Captures stdout+stderr to a log file and returns the command's
# exit status. Designed not to interfere with set -e (uses set +e
# locally) so per-scenario failures don't abort the outer loop.
#
# Usage: run_with_spinner LABEL LOGFILE -- COMMAND [ARGS...]
# ----------------------------------------------------------------------
run_with_spinner() {
  local label="$1"; shift
  local logfile="$1"; shift
  # Consume the "--" separator if present.
  if [[ "${1:-}" == "--" ]]; then shift; fi

  local start; start=$(date +%s)
  ("$@") >"$logfile" 2>&1 &
  local pid=$!

  local spin='|/-\'
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    local elapsed=$(( $(date +%s) - start ))
    printf "\r  %s  %s ... %ds   " "${spin:i++%${#spin}:1}" "$label" "$elapsed"
    sleep 0.4
  done
  local elapsed=$(( $(date +%s) - start ))

  set +e
  wait "$pid"
  local status=$?
  set -e 2>/dev/null || true   # set -e isn't required outside helpers

  if [[ $status -eq 0 ]]; then
    printf "\r  ✓  %s in %ds                                  \n" "$label" "$elapsed"
  else
    printf "\r  ✗  %s FAILED (exit %d, %ds) — see %s\n" \
           "$label" "$status" "$elapsed" "$logfile"
  fi
  return "$status"
}

# Trap Ctrl-C so partial progress is preserved + a parting note printed.
trap '
  echo
  echo "Interrupted at $(date -Iseconds)."
  echo "Partial results in $WORKDIR"
  exit 130
' INT

# ----------------------------------------------------------------------
# Helper: after a step completes, write failures.txt summarising every
# failed scenario + the head/tail of its log file. So inspectability
# does not require opening N per-scenario log files; one summary file
# per step has the relevant excerpts.
#
# Usage: summarize_failures STEP_DIR LOG_PATTERN APP [APP ...]
#   STEP_DIR     where failures.txt is written (e.g. step2_scoring)
#   LOG_PATTERN  printf format with a single %s for the app, e.g.
#                "$STEP_DIR/%s.score"
#   APP...       zero or more failed-app names (use the
#                ${arr[@]+"${arr[@]}"} idiom to pass an array safely
#                under `set -u`)
# ----------------------------------------------------------------------
summarize_failures() {
  local step_dir="$1"
  local log_pattern="$2"
  shift 2
  local out="$step_dir/failures.txt"
  if [[ $# -eq 0 ]]; then
    echo "(no failures)" > "$out"
    return
  fi
  {
    echo "=== Failures from this step ==="
    echo
    for app in "$@"; do
      # shellcheck disable=SC2059
      local logf; logf=$(printf "$log_pattern" "$app")
      echo "--- $app ---"
      if [[ -f "$logf" ]]; then
        echo "  log: $logf"
        echo "  first 8 lines:"
        head -8 "$logf" 2>/dev/null | sed 's/^/    /' || true
        echo "  last 8 lines:"
        tail -8 "$logf" 2>/dev/null | sed 's/^/    /' || true
      else
        echo "  log file missing: $logf"
      fi
      echo
    done
  } > "$out"
  echo "  failures summary written to: $out"
}

# ----------------------------------------------------------------------
# Optional: clean audit DB before step 1
# ----------------------------------------------------------------------
if [[ $KEEP_AUDIT -eq 0 ]]; then
  echo "--- Cleaning audit DB (use --keep-audit to skip) ---"
  bash scripts/clean.sh --audit >/dev/null 2>&1 || true
  echo
fi

# ----------------------------------------------------------------------
# Step 1: run_agents.sh for each scenario
# ----------------------------------------------------------------------
step1_pass=0
step1_fail=0
step1_failed_apps=()
step1_elapsed=0
# CYCLE_MAP is a path (not data); compute it unconditionally so the
# final summary block can echo it whether step 1 ran or not. When
# --skip-to ≥2 the file simply won't exist; the summary still prints
# the path so a human inspecting the workdir can find any prior
# cycle_ids.txt from a previous run.
CYCLE_MAP="$WORKDIR/step1_run_agents/cycle_ids.txt"
if [[ $SKIP_TO -le 1 ]]; then
echo "============================================================"
echo "Step 1/4: Run agent cycles for $TOTAL scenarios"
echo "============================================================"
step1_start=$(date +%s)

: > "$CYCLE_MAP"

for idx in "${!SCENARIOS[@]}"; do
  app="${SCENARIOS[$idx]}"
  n=$((idx + 1))
  printf "[%d/%d] %s\n" "$n" "$TOTAL" "$app"
  log="$WORKDIR/step1_run_agents/${app}.log"
  if run_with_spinner "run_agents $app" "$log" -- bash scripts/run_agents.sh "$app"; then
    step1_pass=$((step1_pass + 1))
    # Parse cycle_id out of the run_agents output and stash it.
    cid=$(grep -E '^cycle_id =' "$log" | head -1 | awk -F'= ' '{print $2}' | tr -d ' ')
    printf "%s %s\n" "$app" "${cid:-MISSING}" >> "$CYCLE_MAP"
  else
    step1_fail=$((step1_fail + 1))
    step1_failed_apps+=("$app")
    printf "%s FAILED\n" "$app" >> "$CYCLE_MAP"
  fi
done

step1_elapsed=$(( $(date +%s) - step1_start ))
echo
echo "Step 1 done: $step1_pass passed, $step1_fail failed, ${step1_elapsed}s elapsed."
summarize_failures "$WORKDIR/step1_run_agents" "$WORKDIR/step1_run_agents/%s.log" ${step1_failed_apps[@]+"${step1_failed_apps[@]}"}
echo
{
  echo "--- Step 1: run_agents ---"
  echo "  passed   : $step1_pass / $TOTAL"
  echo "  failed   : $step1_fail / $TOTAL"
  echo "  elapsed  : ${step1_elapsed}s"
  echo
} >> "$SUMMARY"

else  # SKIP_TO > 1
  echo "============================================================"
  echo "Step 1/4: SKIPPED (--skip-to $SKIP_TO)"
  echo "  Reading existing cycles from audit DB; steps 2-4 will"
  echo "  resolve 'most recent cycle for app-NN' against whatever"
  echo "  is already in .audit_db/audit.db."
  echo "============================================================"
  {
    echo "--- Step 1: run_agents ---"
    echo "  SKIPPED (--skip-to $SKIP_TO)"
    echo
  } >> "$SUMMARY"
fi

# ----------------------------------------------------------------------
# Step 2: score_recommendation.sh for each scenario
#
# Categorization rule. `score_recommendation.sh` exits 1 whenever any
# layer fails — Shape, Correctness, Mid, or Rich. That is a normal
# scoring outcome, NOT a Python crash. The earlier version of this
# block labeled every nonzero exit as "crashed", which conflated three
# very different signals (judge richness fail vs. missing taxonomy
# field vs. actual exception) and made the headline misleading.
#
# Now we parse the layer table out of the .score log and route to the
# right bucket. A real Python exception is the only case with NO
# layer table in the log — that path is tracked as `step2_exception`.
# ----------------------------------------------------------------------
step2_pass=0          # all four layers PASS (or graceful SKIP for no-action)
step2_shape_fail=0    # Shape FAIL (e.g. missing field, malformed prediction)
step2_corr_fail=0     # Shape PASS, Correctness FAIL (wrong taxonomy values)
step2_quality_fail=0  # Shape + Correctness PASS, judge richness FAIL on Mid/Rich
step2_exception=0     # Python exception — no layer table in the log
step2_failed_apps=()
step2_elapsed=0
if [[ $SKIP_TO -le 2 ]]; then
echo "============================================================"
echo "Step 2/4: Score recommendations vs gold answers"
echo "============================================================"
step2_start=$(date +%s)

SCORING_AGG="$WORKDIR/step2_scoring/aggregate.txt"
printf "%-8s %-7s %-12s %-5s %-5s\n" "app" "Shape" "Correctness" "Mid" "Rich" > "$SCORING_AGG"
printf "%-8s %-7s %-12s %-5s %-5s\n" "--------" "-----" "-----------" "---" "----" >> "$SCORING_AGG"

for idx in "${!SCENARIOS[@]}"; do
  app="${SCENARIOS[$idx]}"
  n=$((idx + 1))
  printf "[%d/%d] %s\n" "$n" "$TOTAL" "$app"
  log="$WORKDIR/step2_scoring/${app}.score"
  # Helper: pull the first verdict for a layer name from the .score log.
  # Pattern requires (a) leading whitespace + LAYER + whitespace and
  # (b) a verdict token from the closed set {PASS, FAIL, SKIP, --} right
  # after. `grep -m1` returns only the first match — the .score log can
  # contain the layer table twice (once from the CLI's stdout, once from
  # score_recommendation.sh's head-10 stderr echo on failure), and the
  # earlier loose regex returned multi-line strings that broke the
  # subsequent string-equality checks. Stricter regex + first-match
  # only fixes both issues.
  _layer_verdict() {
    # Drop \b after the verdict group — `--` is not a word character,
    # so \b doesn't match after it and Mid/Rich came back empty for
    # short-circuited (correctness-gated) scenarios. The trailing
    # alternation is anchored at end-of-token by the awk that picks $2.
    grep -m1 -E "^\s*$1\s+(PASS|FAIL|SKIP|--)" "$log" \
      | awk '{print $2}'
  }
  if run_with_spinner "score $app" "$log" -- bash scripts/score_recommendation.sh "$app"; then
    # exit 0 → all four layers passed (SKIP counts as pass).
    sh_v=$(_layer_verdict Shape)
    co_v=$(_layer_verdict Correctness)
    mi_v=$(_layer_verdict Mid)
    ri_v=$(_layer_verdict Rich)
    printf "%-8s %-7s %-12s %-5s %-5s\n" "$app" \
           "${sh_v:-?}" "${co_v:-?}" "${mi_v:-?}" "${ri_v:-?}" >> "$SCORING_AGG"
    step2_pass=$((step2_pass + 1))
  else
    # Non-zero exit. Two possibilities: layer-level scoring failure
    # (normal outcome) or Python exception (real crash). Categorize
    # and print a follow-up line under the spinner ✗ so the operator
    # immediately sees whether to worry. score_recommendation.sh
    # exits 1 on any layer fail — the spinner's "FAILED" tag alone is
    # alarming but mostly benign; the category is the real signal.
    sh_v=$(_layer_verdict Shape)
    if [[ -z "$sh_v" ]]; then
      # No layer table → exception. Render as EXC and bucket separately.
      echo "       └─ Python exception (real crash) — see $log"
      printf "%-8s %-7s %-12s %-5s %-5s\n" "$app" "EXC" "EXC" "EXC" "EXC" >> "$SCORING_AGG"
      step2_exception=$((step2_exception + 1))
    else
      co_v=$(_layer_verdict Correctness)
      mi_v=$(_layer_verdict Mid)
      ri_v=$(_layer_verdict Rich)
      printf "%-8s %-7s %-12s %-5s %-5s\n" "$app" \
             "${sh_v:-?}" "${co_v:-?}" "${mi_v:-?}" "${ri_v:-?}" >> "$SCORING_AGG"
      if [[ "$sh_v" == "FAIL" ]]; then
        echo "       └─ Shape fail — prediction is not well-formed"
        step2_shape_fail=$((step2_shape_fail + 1))
      elif [[ "$co_v" == "FAIL" ]]; then
        echo "       └─ Correctness fail — taxonomy values disagree with gold"
        step2_corr_fail=$((step2_corr_fail + 1))
      else
        # Shape + Correctness both PASS but exit is nonzero → judge
        # richness failure on Mid or Rich. The judge's rationale is
        # in the log and worth surfacing.
        echo "       └─ Mid/Rich fail — judge richness ($mi_v/$ri_v) — see log for judge rationale"
        step2_quality_fail=$((step2_quality_fail + 1))
      fi
    fi
    step2_failed_apps+=("$app")
  fi
done

step2_elapsed=$(( $(date +%s) - step2_start ))
echo
echo "Step 2 done: ${step2_elapsed}s elapsed."
echo "  4/4 PASS         : $step2_pass / $TOTAL"
echo "  Shape fail       : $step2_shape_fail / $TOTAL"
echo "  Correctness fail : $step2_corr_fail / $TOTAL"
echo "  Mid/Rich fail    : $step2_quality_fail / $TOTAL  (judge richness — see .score logs for rationale)"
echo "  Python exception : $step2_exception / $TOTAL  (true crash; if non-zero check failures.txt)"
summarize_failures "$WORKDIR/step2_scoring" "$WORKDIR/step2_scoring/%s.score" ${step2_failed_apps[@]+"${step2_failed_apps[@]}"}
echo
{
  echo "--- Step 2: scoring ---"
  echo "  4/4 PASS         : $step2_pass / $TOTAL"
  echo "  Shape fail       : $step2_shape_fail / $TOTAL"
  echo "  Correctness fail : $step2_corr_fail / $TOTAL"
  echo "  Mid/Rich fail    : $step2_quality_fail / $TOTAL"
  echo "  Python exception : $step2_exception / $TOTAL"
  echo "  elapsed          : ${step2_elapsed}s"
  echo "  table            : $SCORING_AGG"
  echo
} >> "$SUMMARY"

else  # SKIP_TO > 2
  echo "============================================================"
  echo "Step 2/4: SKIPPED (--skip-to $SKIP_TO)"
  echo "============================================================"
  { echo "--- Step 2: scoring ---"; echo "  SKIPPED (--skip-to $SKIP_TO)"; echo; } >> "$SUMMARY"
fi

# ----------------------------------------------------------------------
# Step 3: verify_evidence_chain.sh for each scenario
# ----------------------------------------------------------------------
step3_clean=0
step3_dirty=0
step3_fail=0
step3_failed_apps=()
step3_elapsed=0
if [[ $SKIP_TO -le 3 ]]; then
echo "============================================================"
echo "Step 3/4: Verify evidence chains"
echo "============================================================"
step3_start=$(date +%s)

VERIFY_AGG="$WORKDIR/step3_evidence_chain/aggregate.txt"
printf "%-8s %-7s %-10s %-9s\n" "app" "cited" "resolved" "dangling" > "$VERIFY_AGG"
printf "%-8s %-7s %-10s %-9s\n" "--------" "-----" "--------" "--------" >> "$VERIFY_AGG"

for idx in "${!SCENARIOS[@]}"; do
  app="${SCENARIOS[$idx]}"
  n=$((idx + 1))
  printf "[%d/%d] %s\n" "$n" "$TOTAL" "$app"
  log="$WORKDIR/step3_evidence_chain/${app}.verify"
  # verify_evidence_chain.sh exits 1 on dangling refs, but we still want
  # to capture the counts. Let it return nonzero without aborting.
  run_with_spinner "verify $app" "$log" -- bash scripts/verify_evidence_chain.sh "$app"
  v_status=$?
  cited=$(grep -E 'unique refs cited' "$log" | awk '{print $NF}')
  resolved=$(grep -E 'resolved cleanly' "$log" | awk '{print $NF}')
  dangling=$(grep -E 'DANGLING \(unresolved\)' "$log" | awk '{print $NF}')
  printf "%-8s %-7s %-10s %-9s\n" "$app" \
         "${cited:-?}" "${resolved:-?}" "${dangling:-?}" >> "$VERIFY_AGG"
  if [[ "${dangling:-1}" == "0" ]]; then
    step3_clean=$((step3_clean + 1))
  elif [[ -n "${dangling:-}" ]]; then
    step3_dirty=$((step3_dirty + 1))
    step3_failed_apps+=("$app")
  else
    step3_fail=$((step3_fail + 1))
    step3_failed_apps+=("$app")
  fi
done

step3_elapsed=$(( $(date +%s) - step3_start ))
echo
echo "Step 3 done: $step3_clean clean, $step3_dirty dangling, $step3_fail crashed. ${step3_elapsed}s elapsed."
summarize_failures "$WORKDIR/step3_evidence_chain" "$WORKDIR/step3_evidence_chain/%s.verify" ${step3_failed_apps[@]+"${step3_failed_apps[@]}"}
echo
{
  echo "--- Step 3: evidence-chain verify ---"
  echo "  clean    : $step3_clean / $TOTAL"
  echo "  dangling : $step3_dirty / $TOTAL"
  echo "  crashed  : $step3_fail / $TOTAL"
  echo "  elapsed  : ${step3_elapsed}s"
  echo "  table    : $VERIFY_AGG"
  echo
} >> "$SUMMARY"

else  # SKIP_TO > 3
  echo "============================================================"
  echo "Step 3/4: SKIPPED (--skip-to $SKIP_TO)"
  echo "============================================================"
  { echo "--- Step 3: evidence-chain verify ---"; echo "  SKIPPED (--skip-to $SKIP_TO)"; echo; } >> "$SUMMARY"
fi

# ----------------------------------------------------------------------
# Step 4: render human report + JSON trace for each scenario
# ----------------------------------------------------------------------
step4_pass=0
step4_fail=0
step4_failed_apps=()
step4_elapsed=0
if [[ $SKIP_TO -le 4 ]]; then
echo "============================================================"
echo "Step 4/4: Render human reports + evidence traces"
echo "============================================================"
step4_start=$(date +%s)

for idx in "${!SCENARIOS[@]}"; do
  app="${SCENARIOS[$idx]}"
  n=$((idx + 1))
  printf "[%d/%d] %s\n" "$n" "$TOTAL" "$app"
  outdir="$WORKDIR/step4_reports/$app"
  mkdir -p "$outdir"
  # Each scenario produces three artifacts. If any of the three fails,
  # mark the scenario as failed but continue to the next.
  ok=1
  run_with_spinner "report $app" "$outdir/render.log" -- bash scripts/render_recommendation.sh "$app" --out "$outdir/report.md" \
    || ok=0
  run_with_spinner "trace.md $app" "$outdir/trace_md.log" -- bash scripts/render_evidence_trace.sh "$app" --format markdown --out "$outdir/trace.md" \
    || ok=0
  run_with_spinner "trace.json $app" "$outdir/trace_json.log" -- bash scripts/render_evidence_trace.sh "$app" --format json --out "$outdir/trace.json" \
    || ok=0
  if [[ $ok -eq 1 ]]; then
    step4_pass=$((step4_pass + 1))
  else
    step4_fail=$((step4_fail + 1))
    step4_failed_apps+=("$app")
  fi
done

step4_elapsed=$(( $(date +%s) - step4_start ))
echo
echo "Step 4 done: $step4_pass full trio, $step4_fail partial/failed. ${step4_elapsed}s elapsed."
# Step 4 has three render logs per app; the most useful for diagnosis
# is render.log (the human report — the one that's been failing).
summarize_failures "$WORKDIR/step4_reports" "$WORKDIR/step4_reports/%s/render.log" ${step4_failed_apps[@]+"${step4_failed_apps[@]}"}
echo
{
  echo "--- Step 4: report rendering ---"
  echo "  full trio (report + trace.md + trace.json) : $step4_pass / $TOTAL"
  echo "  partial / failed                           : $step4_fail / $TOTAL"
  echo "  elapsed                                    : ${step4_elapsed}s"
  echo
} >> "$SUMMARY"

else  # SKIP_TO > 4 — not reachable today (arg parsing rejects), kept for symmetry
  echo "============================================================"
  echo "Step 4/4: SKIPPED (--skip-to $SKIP_TO)"
  echo "============================================================"
  { echo "--- Step 4: report rendering ---"; echo "  SKIPPED (--skip-to $SKIP_TO)"; echo; } >> "$SUMMARY"
fi

# ----------------------------------------------------------------------
# Final aggregate
# ----------------------------------------------------------------------
RUN_ELAPSED=$(( $(date +%s) - RUN_START ))
{
  echo "=== Integration test complete ==="
  echo "Finished    : $(date -Iseconds)"
  echo "Total time  : ${RUN_ELAPSED}s ($((RUN_ELAPSED / 60))m $((RUN_ELAPSED % 60))s)"
  echo
  echo "Per-step elapsed:"
  echo "  step1 (run_agents)    : ${step1_elapsed}s"
  echo "  step2 (score)         : ${step2_elapsed}s"
  echo "  step3 (verify chain)  : ${step3_elapsed}s"
  echo "  step4 (render reports): ${step4_elapsed}s"
  echo
  echo "Headline:"
  echo "  step2 4/4 PASS        : $step2_pass / $TOTAL  (gold-quality recommendations)"
  echo "  step2 Shape fail      : $step2_shape_fail / $TOTAL"
  echo "  step2 Correctness fail: $step2_corr_fail / $TOTAL"
  echo "  step2 Mid/Rich fail   : $step2_quality_fail / $TOTAL  (judge richness)"
  echo "  step2 Python exception: $step2_exception / $TOTAL  (true crash)"
  echo "  step3 zero-dangling   : $step3_clean / $TOTAL  (clean evidence chains)"
  echo
  echo "Inspect:"
  echo "  scoring table  : $SCORING_AGG"
  echo "  verify table   : $VERIFY_AGG"
  echo "  cycle id map   : $CYCLE_MAP"
  echo "  reports        : $WORKDIR/step4_reports/app-NN/"
} | tee -a "$SUMMARY"

echo
echo "============================================================"
echo "All four steps complete. Total: ${RUN_ELAPSED}s ($((RUN_ELAPSED / 60))m)"
echo "Summary: $SUMMARY"
echo "============================================================"
