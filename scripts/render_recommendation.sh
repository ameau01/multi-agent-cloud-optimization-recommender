#!/usr/bin/env bash
# Render the agent's recommendation as a markdown report — the same
# format as sample_runs/reports/scenario_NN_report.md, just produced
# from a live agent cycle instead of a gold composite.
#
# The agent's produce_synthesis schema doesn't populate every field a full
# gold composite has (no report_content, no trace section, no rich
# trade-off table). The renderer handles that gracefully and produces a
# degenerate report — title + final-recommendation table + reasoning
# prose. Once the agent's output is richer, this script produces a
# richer report automatically.
#
# Usage:
#   scripts/render_recommendation.sh <app-NN> [CYCLE_ID] [--out FILE]
#
# Args:
#   app-NN              The application (e.g. app-08). Required.
#   CYCLE_ID            Optional. Defaults to the most recent cycle for app-NN.
#
# Flags:
#   --out FILE          Write to FILE instead of stdout.
#   -h, --help          Show this help message and exit.
#
# Examples:
#   scripts/render_recommendation.sh app-08
#   scripts/render_recommendation.sh app-08 --out /tmp/report.md
#   scripts/render_recommendation.sh app-08 cycle_20260603_111542_23536842

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -e
cd "$(dirname "$0")/.."

APP_NAME="${1:-}"
shift || true

if [[ -z "$APP_NAME" ]]; then
  echo "Usage: scripts/render_recommendation.sh <app-NN> [CYCLE_ID] [--out FILE]" >&2
  exit 2
fi

CYCLE_ID=""
OUT_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_FILE="$2"; shift 2 ;;
    cycle_*) CYCLE_ID="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Quoted heredoc ('PY') disables bash expansion inside the body — so
# backticks in Python comments don't get parsed as command substitution
# (was breaking the first version of this script). Bash vars get passed
# as positional args via sys.argv instead.
uv run python - "$APP_NAME" "$CYCLE_ID" "$OUT_FILE" <<'PY'
"""Pull the cycle's recommendation, map it to a Recommendation Pydantic
object, render the markdown report, write to stdout or --out."""

import re
import sys
from pathlib import Path

from src.audit.inspect import _resolve_target
from src.audit.queries import get_cycle_events
from src.common.init import get_audit_store
from src.models.composite import Recommendation
from src.renderer import render_report

app_name = sys.argv[1]
cycle_id_in = sys.argv[2] or None
out_file = sys.argv[3] or None

# Map "app-08" -> scenario id "08" (matches eval-set/expectations layout).
m = re.match(r"^app-(\d{2})$", app_name)
if not m:
    print(f"ERROR: expected 'app-NN' (e.g. app-08), got {app_name!r}",
          file=sys.stderr)
    sys.exit(2)
sid = m.group(1)

store = get_audit_store()
cycle_id = _resolve_target(store, app_name, cycle_id_in)

events = get_cycle_events(store, cycle_id)
rec_rows = [e for e in events if e.type == "recommendation"]
if not rec_rows:
    print(
        f"No recommendation row in cycle {cycle_id} (app={app_name}). "
        f"Cycle may have ended at restraint, deferral, or failure.",
        file=sys.stderr,
    )
    sys.exit(1)

rec_content = rec_rows[-1].content
composite_in = rec_content.get("composite") or {}
# Coerce: langchain-anthropic occasionally serializes the nested
# `recommendation` object as a JSON string instead of a dict.
if isinstance(composite_in, str):
    import json as _json
    try:
        composite_in = _json.loads(composite_in)
    except _json.JSONDecodeError:
        composite_in = {}
if not isinstance(composite_in, dict):
    composite_in = {}
evidence_refs = rec_content.get("evidence_refs") or []

# Three-step reasoning sub-objects, persisted by the Cross-Tier
# Evaluator's _record_recommendation. These carry the named-section
# content the gold sample_runs reports show (summary, specialist
# findings, cross-tier analysis, trade-off analysis, evaluator
# confidence). The renderer module itself is still recommendation-
# shaped; we surface the new content here as an appended block so
# re-runs are inspectable without waiting on a full renderer rewrite.
import json as _json
def _coerce(value):
    if isinstance(value, str) and value:
        try: return _json.loads(value)
        except _json.JSONDecodeError: return {}
    return value if isinstance(value, dict) else {}

def _coerce_optional(value):
    """Like _coerce but returns None for missing/unparseable values, so
    Optional Pydantic fields stay None rather than getting an empty
    sub-model that fails validation on required keys."""
    if value is None:
        return None
    if isinstance(value, str) and value:
        try:
            parsed = _json.loads(value)
        except _json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return value if isinstance(value, dict) else None

reconciliation_in = _coerce(rec_content.get("reconciliation"))
reflection_in = _coerce(rec_content.get("reflection"))

# Map the agent dict to a Recommendation. produce_synthesis now produces
# specific_change as a required field; prefer it. Older cycles run
# before that schema change won't have it -- fall back to reasoning
# then headline so this script still works on legacy audit data.
specific_change = (
    composite_in.get("specific_change")
    or composite_in.get("reasoning")
    or composite_in.get("headline")
    or "(agent did not populate a specific_change field)"
)

rec = Recommendation(
    scenario_id=sid,
    specific_change=specific_change,
    finding_type=composite_in.get("finding_type"),
    primary_tier=composite_in.get("primary_tier"),
    secondary_tier=composite_in.get("secondary_tier"),
    action_category=composite_in.get("action_category"),
    reasoning=composite_in.get("reasoning"),
    # Pass the structured sub-objects through too. Recommendation
    # accepts them as Pydantic sub-models; render_report's downstream
    # sections key off them (evidence anchors, projected state notes,
    # cost impact). Without these the report degrades to title +
    # final-recommendation table only.
    #
    # _coerce_optional handles two failure modes we observed in the
    # 18-scenario integration test: (a) langchain-anthropic serializes
    # the nested object as a JSON string instead of a dict, and (b) for
    # restraint/deferral cycles the field is absent entirely. The helper
    # returns None when the field is missing or unparseable, which keeps
    # the Optional Pydantic field happy rather than failing construction
    # with an empty {} that doesn't validate.
    evidence=_coerce_optional(composite_in.get("evidence")),
    projected_state=_coerce_optional(composite_in.get("projected_state")),
    cost_impact=_coerce_optional(composite_in.get("cost_impact")),
)

# render_report's signature is typed against Composite but accepts a
# Recommendation via the getattr fallback we added — sections sourced
# from report_content are simply skipped, and the output is the
# degenerate report (title, final-recommendation table, specific_change
# prose).
markdown = render_report(rec)  # type: ignore[arg-type]

# Append the three-step reasoning sub-objects as named sections so the
# rendered output reflects the agent's full reasoning chain, matching
# the gold sample_runs report shape (summary, specialist findings,
# cross-tier analysis, trade-off analysis, evaluator confidence).

def _section_summary(rec_dict):
    summary = rec_dict.get("summary")
    if not summary: return ""
    return f"\n---\n\n## Summary\n\n{summary}\n"

def _section_specialist_findings(reconciliation):
    topology = reconciliation.get("topology_assessment") or ""
    rows = reconciliation.get("specialist_findings_summary") or []
    if not topology and not rows: return ""
    out = "\n---\n\n## Specialist findings\n\n"
    if topology: out += f"{topology}\n\n"
    if rows:
        out += "| Agent | Finding type | Confidence | Key observation | Evidence refs |\n"
        out += "|---|---|---|---|---|\n"
        for r in rows:
            agent = r.get("agent", "")
            ft = r.get("finding_type", "")
            conf = r.get("confidence", "")
            ko = (r.get("key_observation") or "").replace("\n", " ")
            er = r.get("evidence_refs") or []
            out += f"| {agent} | `{ft}` | {conf} | {ko} | {er} |\n"
    return out

def _section_cross_tier(reconciliation):
    drift = reconciliation.get("drift_check") or []
    corr = reconciliation.get("cross_tier_correlations") or []
    conflict = reconciliation.get("conflict_resolution") or ""
    if not (drift or corr or conflict): return ""
    out = "\n---\n\n## Cross-tier analysis\n\n"
    if drift:
        out += "**Drift-check.**\n\n"
        for d in drift:
            out += (f"- _{d.get('agent','')}_ ({d.get('verdict','')}): "
                    f"{d.get('narrative','')}\n")
        out += "\n"
    if corr:
        out += "**Cross-tier correlations.**\n\n"
        out += "| Tier A | Tier B | Coefficient | Lag (min) | Interpretation | Evidence ref |\n"
        out += "|---|---|---|---|---|---|\n"
        for c in corr:
            # Render evidence_ref as a code-spanned id, or "(evaluator-inferred)"
            # when the LLM produced the correlation without anchoring to a
            # specific observation row. Visible mark beats silent omission.
            er = c.get("evidence_ref")
            er_cell = f"`{er}`" if isinstance(er, int) else "(evaluator-inferred)"
            out += (f"| {c.get('tier_a','')} | {c.get('tier_b','')} | "
                    f"{c.get('coefficient','')} | {c.get('lag_minutes','')} | "
                    f"{c.get('interpretation','')} | {er_cell} |\n")
        out += "\n"
    if conflict:
        out += f"**Conflict resolution.** {conflict}\n"
    return out

def _section_trade_off(reflection):
    rows = reflection.get("trade_off_analysis") or []
    philosophy = reflection.get("trade_off_philosophy") or ""
    if not (rows or philosophy): return ""
    out = "\n---\n\n## Trade-off analysis\n\n"
    if rows:
        out += "| Dimension | Value | Note |\n|---|---|---|\n"
        for r in rows:
            out += (f"| {r.get('dimension','')} | {r.get('value','')} | "
                    f"{r.get('note','')} |\n")
    if philosophy: out += f"\n{philosophy}\n"
    return out

def _section_confidence(reflection):
    level = reflection.get("evaluator_confidence_level") or ""
    narrative = reflection.get("evaluator_confidence_narrative") or ""
    if not (level or narrative): return ""
    # The LLM tends to start the narrative with the same level word the
    # renderer prefixes, producing "**High.** High. Drift-check is...".
    # Strip a leading level word (case-insensitive, optional ., trailing
    # whitespace) when it matches the level field.
    if level and narrative:
        import re as _re
        narrative = _re.sub(
            rf'^\s*{_re.escape(level)}\.?\s+', '', narrative,
            count=1, flags=_re.IGNORECASE,
        )
    return (f"\n---\n\n## Evaluator confidence\n\n"
            f"**{level.capitalize() if level else 'N/A'}.** {narrative}\n")

# Tail with the new sections + the existing Provenance section.
extra = (
    _section_summary(composite_in)
    + _section_specialist_findings(reconciliation_in)
    + _section_cross_tier(reconciliation_in)
    + _section_trade_off(reflection_in)
    + _section_confidence(reflection_in)
)

footer = (
    "\n---\n\n## Provenance\n\n"
    f"- Cycle: {cycle_id}\n"
    f"- Application: {app_name}\n"
    f"- Evidence refs (audit_records ids): {evidence_refs}\n"
    "\n"
    "Inspect the full audit + harness trail with:\n\n"
    f"    scripts/show_audit_trail.sh {app_name} {cycle_id}\n"
)
markdown = markdown.rstrip() + extra + "\n" + footer

if out_file:
    Path(out_file).write_text(markdown)
    print(f"Wrote {len(markdown)} bytes to {out_file}", file=sys.stderr)
else:
    sys.stdout.write(markdown)
PY
