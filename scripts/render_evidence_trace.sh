#!/usr/bin/env bash
# Render the full evidence chain for one cycle as either machine-readable
# JSON or human-readable structured markdown. The live-cycle equivalent
# of sample_runs/traces/scenario_NN_trace.json.
#
# For every evidence_ref the recommendation cites (top-level on the row,
# inside reconciliation sub-objects, and in prose), expands it inline
# to:
#   - the observation row's full content (tool response body)
#   - the parent tool_call row's args (one hop back through parent_id)
#   - the list of sources that cited it
#
# Distinct from render_recommendation.sh: that produces the human-facing
# report with prose-style citations. This produces the chain itself,
# mechanically resolved, with every claim's evidence colocated.
#
# Usage:
#   scripts/render_evidence_trace.sh <app-NN> [CYCLE_ID] [--format FORMAT]
#
# Args:
#   app-NN              The application (e.g. app-08). Required.
#   CYCLE_ID            Optional. Defaults to the most recent cycle for app-NN.
#
# Flags:
#   --format FORMAT     "json" or "markdown" (default markdown).
#   --out FILE          Write to FILE instead of stdout.
#   -h, --help          Show this help message and exit.
#
# Examples:
#   scripts/render_evidence_trace.sh app-08
#   scripts/render_evidence_trace.sh app-08 --format json
#   scripts/render_evidence_trace.sh app-08 --format json --out trace.json
#   scripts/render_evidence_trace.sh app-08 cycle_20260603_173749_a969d7bc --format markdown --out trace.md

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -e
cd "$(dirname "$0")/.."

APP_NAME="${1:-}"
shift || true

if [[ -z "$APP_NAME" ]]; then
  echo "Usage: scripts/render_evidence_trace.sh <app-NN> [CYCLE_ID] [--format FORMAT] [--out FILE]" >&2
  exit 2
fi

CYCLE_ID=""
FORMAT="markdown"
OUT_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --format) FORMAT="$2"; shift 2 ;;
    --out)    OUT_FILE="$2"; shift 2 ;;
    cycle_*)  CYCLE_ID="$1"; shift ;;
    *)        echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ "$FORMAT" != "json" && "$FORMAT" != "markdown" ]]; then
  echo "ERROR: --format must be 'json' or 'markdown', got: $FORMAT" >&2
  exit 2
fi

uv run python - "$APP_NAME" "$CYCLE_ID" "$FORMAT" "$OUT_FILE" <<'PY'
"""Render the evidence chain for one cycle. Pull every cited evidence_ref,
look up its row + its parent tool_call, and assemble the trace.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.audit.inspect import _resolve_target
from src.audit.queries import get_cycle_events
from src.common.init import get_audit_store

app_name = sys.argv[1]
cycle_id_in = sys.argv[2] or None
output_format = sys.argv[3]
out_file = sys.argv[4] or None

store = get_audit_store()
cycle_id = _resolve_target(store, app_name, cycle_id_in)

events = get_cycle_events(store, cycle_id)
events_by_id: dict[int, Any] = {e.id: e for e in events if e.id is not None}

rec_rows = [e for e in events if e.type == "recommendation"]
if not rec_rows:
    print(
        f"No recommendation row in cycle {cycle_id} (app={app_name}).",
        file=sys.stderr,
    )
    sys.exit(1)

rec = rec_rows[-1]
rec_content = rec.content


def _coerce_dict(value: Any) -> dict[str, Any]:
    """langchain-anthropic occasionally serializes nested dicts as JSON
    strings. Coerce so the rest of the pipeline can treat them as dicts."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


composite = _coerce_dict(rec_content.get("composite"))
reconciliation = _coerce_dict(rec_content.get("reconciliation"))
reflection = _coerce_dict(rec_content.get("reflection"))

# ----------------------------------------------------------------------
# Step 1: collect every cited evidence_ref + where it was cited.
# Mirrors the verify_evidence_chain.sh collection logic.
# ----------------------------------------------------------------------
sources_by_ref: dict[int, list[str]] = defaultdict(list)


def _record(source: str, ids: Any) -> None:
    if isinstance(ids, int):
        sources_by_ref[ids].append(source)
    elif isinstance(ids, list):
        for x in ids:
            if isinstance(x, int):
                sources_by_ref[x].append(source)


_record("recommendation.evidence_refs", rec_content.get("evidence_refs") or [])

for i, row in enumerate(reconciliation.get("specialist_findings_summary") or []):
    _record(
        f"reconciliation.specialist_findings_summary[{i}].evidence_refs",
        row.get("evidence_refs"),
    )
for i, row in enumerate(reconciliation.get("drift_check") or []):
    _record(
        f"reconciliation.drift_check[{i}].supporting_evidence_refs",
        row.get("supporting_evidence_refs"),
    )
for i, row in enumerate(reconciliation.get("cross_tier_correlations") or []):
    _record(
        f"reconciliation.cross_tier_correlations[{i}].evidence_ref",
        row.get("evidence_ref"),
    )

PROSE_REF_RE = re.compile(
    r"evidence[_\s]ref(?:s)?\s*[:=]\s*([\d,\s]+)",
    re.IGNORECASE,
)


def _scan_prose(label: str, text: str) -> None:
    if not isinstance(text, str) or not text:
        return
    for match in PROSE_REF_RE.finditer(text):
        ids_str = match.group(1).strip().rstrip(",")
        ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
        for x in ids:
            sources_by_ref[x].append(f"{label} (prose @ char {match.start()})")


_scan_prose("composite.specific_change", composite.get("specific_change") or "")
_scan_prose("composite.summary", composite.get("summary") or "")
_scan_prose("composite.reasoning", composite.get("reasoning") or "")
_scan_prose("composite.headline", composite.get("headline") or "")
for i, row in enumerate(reconciliation.get("drift_check") or []):
    _scan_prose(
        f"reconciliation.drift_check[{i}].narrative",
        row.get("narrative") or "",
    )
for i, row in enumerate(reconciliation.get("cross_tier_correlations") or []):
    _scan_prose(
        f"reconciliation.cross_tier_correlations[{i}].interpretation",
        row.get("interpretation") or "",
    )
_scan_prose(
    "reconciliation.topology_assessment",
    reconciliation.get("topology_assessment") or "",
)
_scan_prose(
    "reconciliation.conflict_resolution",
    reconciliation.get("conflict_resolution") or "",
)
_scan_prose(
    "reflection.evaluator_confidence_narrative",
    reflection.get("evaluator_confidence_narrative") or "",
)
_scan_prose(
    "reflection.trade_off_philosophy",
    reflection.get("trade_off_philosophy") or "",
)
for i, row in enumerate(reflection.get("trade_off_analysis") or []):
    _scan_prose(
        f"reflection.trade_off_analysis[{i}].note",
        row.get("note") or "",
    )

# ----------------------------------------------------------------------
# Step 2: resolve every cited id + walk one hop back to the parent
# tool_call (when the cited row is an observation, the tool_call args
# tell us WHAT the agent asked for that produced this observation).
# ----------------------------------------------------------------------
chain: dict[int, dict[str, Any]] = {}

for ref in sorted(sources_by_ref.keys()):
    row = events_by_id.get(ref)
    if row is None:
        chain[ref] = {
            "id": ref,
            "status": "DANGLING",
            "cited_by": sources_by_ref[ref],
        }
        continue
    entry: dict[str, Any] = {
        "id": row.id,
        "status": "resolved",
        "type": row.type,
        "agent": row.agent,
        "category": row.category,
        "timestamp": str(getattr(row, "timestamp", "")) or None,
        "parent_id": row.parent_id,
        "cited_by": sources_by_ref[ref],
        "content": row.content,
    }
    if row.type == "observation":
        entry["tool_name"] = (row.content or {}).get("tool_name")
        # Walk one hop back to the matching tool_call row. The observation's
        # parent_id points at the tool_call that produced it.
        parent = events_by_id.get(row.parent_id) if row.parent_id else None
        if parent is not None and parent.type == "tool_call":
            entry["tool_call"] = {
                "id": parent.id,
                "tool_name": (parent.content or {}).get("tool_name"),
                "args": (parent.content or {}).get("arguments") or
                        (parent.content or {}).get("args") or {},
            }
    chain[ref] = entry

# ----------------------------------------------------------------------
# Step 3: assemble the specialist-finding hop. The top-level
# recommendation.evidence_refs lists the contributing specialist rows;
# pull each one's full content (which itself contains evidence_refs +
# headline + reasoning_summary).
# ----------------------------------------------------------------------
specialist_findings: list[dict[str, Any]] = []
for rid in rec_content.get("evidence_refs") or []:
    if not isinstance(rid, int):
        continue
    sf = events_by_id.get(rid)
    if sf is None or sf.type != "specialist_finding":
        continue
    specialist_findings.append({
        "id": sf.id,
        "agent": sf.agent,
        "timestamp": str(getattr(sf, "timestamp", "")) or None,
        "content": sf.content,
        "evidence_refs_chain": [
            {
                "ref": r,
                "type": (events_by_id.get(r) or type("x", (), {"type": "?"})()).type,
                "tool_name": (events_by_id.get(r).content or {}).get("tool_name")
                             if events_by_id.get(r) else None,
                "resolved": r in events_by_id,
            }
            for r in (sf.content or {}).get("evidence_refs") or []
            if isinstance(r, int)
        ],
    })

# ----------------------------------------------------------------------
# Step 4: assemble the trace object.
# ----------------------------------------------------------------------
trace = {
    "cycle_id": cycle_id,
    "application_id": app_name,
    "recommendation_row_id": rec.id,
    "recommendation": {
        "composite": composite,
        "reconciliation": reconciliation,
        "reflection": reflection,
    },
    "specialist_findings": specialist_findings,
    "evidence_chain": {str(k): v for k, v in chain.items()},
    "summary": {
        "unique_refs_cited": len(sources_by_ref),
        "resolved": sum(1 for v in chain.values() if v.get("status") == "resolved"),
        "dangling": sum(1 for v in chain.values() if v.get("status") == "DANGLING"),
        "observation_refs": sum(1 for v in chain.values() if v.get("type") == "observation"),
        "specialist_finding_refs": sum(1 for v in chain.values() if v.get("type") == "specialist_finding"),
    },
}

# ----------------------------------------------------------------------
# Step 5: render in the requested format.
# ----------------------------------------------------------------------
if output_format == "json":
    output = json.dumps(trace, indent=2, default=str)
else:
    # Structured markdown: every ref gets its own section with the cited-by
    # list, the tool_call args, and the observation body inlined.
    out: list[str] = []
    out.append(f"# Evidence Trace — {app_name}")
    out.append("")
    out.append(f"**Cycle.** `{cycle_id}`")
    out.append(f"**Recommendation row.** `{rec.id}`")
    out.append(f"**Refs cited.** {trace['summary']['unique_refs_cited']} "
               f"({trace['summary']['resolved']} resolved, "
               f"{trace['summary']['dangling']} dangling)")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## Recommendation summary")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(f"| finding_type | `{composite.get('finding_type', '-')}` |")
    out.append(f"| primary_tier | `{composite.get('primary_tier', '-')}` |")
    out.append(f"| secondary_tier | `{composite.get('secondary_tier', '-')}` |")
    out.append(f"| action_category | `{composite.get('action_category', '-')}` |")
    out.append(f"| headline | {composite.get('headline', '-')} |")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## Specialist findings chain")
    out.append("")
    out.append("Top-level `recommendation.evidence_refs` cites these "
               "specialist findings, each of which cites its own "
               "observations (one hop deeper).")
    out.append("")
    for sf in specialist_findings:
        out.append(f"### Specialist finding row {sf['id']} — {sf['agent']}")
        out.append("")
        sf_content = sf.get("content") or {}
        out.append(f"- **finding_type:** `{sf_content.get('finding_type', '-')}`")
        out.append(f"- **primary_tier:** `{sf_content.get('primary_tier', '-')}`")
        out.append(f"- **confidence:** {sf_content.get('confidence', '-')}")
        headline = sf_content.get("headline", "")
        if headline:
            out.append(f"- **headline:** {headline}")
        out.append(f"- **evidence_refs cited by this specialist:**")
        out.append("")
        if not sf["evidence_refs_chain"]:
            out.append("  (none)")
        else:
            for ref_entry in sf["evidence_refs_chain"]:
                marker = "✓" if ref_entry["resolved"] else "DANGLING"
                tool = ref_entry.get("tool_name") or "-"
                out.append(f"  - {marker} `ref={ref_entry['ref']}` "
                           f"type=`{ref_entry['type']}` tool=`{tool}`")
        out.append("")
    out.append("---")
    out.append("")
    out.append("## Evidence chain (every cited ref, resolved)")
    out.append("")
    out.append("Each entry below is one audit_records row the recommendation "
               "cites somewhere. For observation rows, the parent tool_call's "
               "args are inlined so the chain reads "
               "`tool_call(args) → observation(body) → cited by N sources`.")
    out.append("")
    for ref in sorted(chain.keys()):
        entry = chain[ref]
        if entry.get("status") == "DANGLING":
            out.append(f"### ref={ref} — DANGLING")
            out.append("")
            out.append("**Cited by:**")
            for src in entry["cited_by"]:
                out.append(f"- {src}")
            out.append("")
            continue
        tool_name = entry.get("tool_name") or "-"
        header = (f"### ref={ref} — `{entry['type']}` "
                  f"(agent=`{entry['agent']}`, tool=`{tool_name}`)")
        out.append(header)
        out.append("")
        out.append(f"**Cited by ({len(entry['cited_by'])} source"
                   f"{'s' if len(entry['cited_by']) != 1 else ''}):**")
        out.append("")
        for src in entry["cited_by"]:
            out.append(f"- {src}")
        out.append("")
        tc = entry.get("tool_call")
        if tc:
            out.append(f"**Tool call** (row {tc['id']}):")
            out.append("")
            out.append("```json")
            out.append(json.dumps(tc.get("args") or {}, indent=2, default=str))
            out.append("```")
            out.append("")
        out.append("**Observation body:**")
        out.append("")
        out.append("```json")
        out.append(json.dumps(entry["content"], indent=2, default=str))
        out.append("```")
        out.append("")
    output = "\n".join(out) + "\n"

# ----------------------------------------------------------------------
# Step 6: write out.
# ----------------------------------------------------------------------
if out_file:
    Path(out_file).write_text(output)
    print(f"Wrote {len(output)} bytes to {out_file}", file=sys.stderr)
else:
    sys.stdout.write(output)
PY
