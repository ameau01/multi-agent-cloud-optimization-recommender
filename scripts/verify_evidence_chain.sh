#!/usr/bin/env bash
# Verify that every evidence_ref cited in a recommendation resolves to a
# real audit_records row in the same cycle. Walks the chain top-down:
#
#   recommendation row
#     -> contributing specialist_finding rows
#         -> their evidence_refs (audit_records observation rows)
#   recommendation row
#     -> reconciliation.specialist_findings_summary[*].evidence_refs
#     -> reconciliation.drift_check[*].supporting_evidence_refs
#     -> reconciliation.cross_tier_correlations[*].evidence_ref
#   prose fields (specific_change, summary, drift narratives, etc.)
#     -> every "evidence_ref(s)=NN" pattern extracted with regex
#
# For each cited id, looks up the row in audit_records and reports its
# type, agent, and tool. Dangling references (cited but not in the DB)
# print as DANGLING and the script exits non-zero.
#
# Usage:
#   scripts/verify_evidence_chain.sh <app-NN> [CYCLE_ID]
#
# Args:
#   app-NN              The application (e.g. app-08). Required.
#   CYCLE_ID            Optional. Defaults to the most recent cycle for app-NN.
#
# Flags:
#   --verbose           Print every cited id, not just summary + dangling.
#   -h, --help          Show this help message and exit.
#
# Examples:
#   scripts/verify_evidence_chain.sh app-08
#   scripts/verify_evidence_chain.sh app-08 --verbose
#   scripts/verify_evidence_chain.sh app-08 cycle_20260603_173749_a969d7bc

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

set -e
cd "$(dirname "$0")/.."

APP_NAME="${1:-}"
shift || true

if [[ -z "$APP_NAME" ]]; then
  echo "Usage: scripts/verify_evidence_chain.sh <app-NN> [CYCLE_ID] [--verbose]" >&2
  exit 2
fi

CYCLE_ID=""
VERBOSE="False"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose) VERBOSE="True"; shift ;;
    cycle_*) CYCLE_ID="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

uv run python - "$APP_NAME" "$CYCLE_ID" "$VERBOSE" <<'PY'
"""Walk every evidence_ref cited in a cycle's recommendation and verify
each resolves to a real audit_records row. Reports the chain and any
dangling references. Exit code 0 = all resolved; 1 = dangling refs."""

import json
import re
import sys
from collections import defaultdict
from typing import Any

from src.audit.inspect import _resolve_target
from src.audit.queries import get_cycle_events
from src.common.init import get_audit_store

app_name = sys.argv[1]
cycle_id_in = sys.argv[2] or None
verbose = sys.argv[3] == "True"

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
    """langchain-anthropic sometimes serializes dicts as JSON strings."""
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
# Step 1: collect every cited evidence_ref into a structured map.
# key = source-of-citation (e.g. "specialist_findings_summary[0]")
# val = list of cited ids
# ----------------------------------------------------------------------
cited: dict[str, list[int]] = {}


def _record(source: str, ids: Any) -> None:
    if isinstance(ids, int):
        cited.setdefault(source, []).append(ids)
    elif isinstance(ids, list):
        valid = [x for x in ids if isinstance(x, int)]
        if valid:
            cited.setdefault(source, []).extend(valid)


# Top-level evidence_refs on the recommendation row itself (specialist
# finding row ids that contributed).
_record(
    "recommendation.evidence_refs",
    rec_content.get("evidence_refs") or [],
)

# Reconciliation structured fields.
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

# Prose fields — extract every "evidence_ref(s)=NN, MM" with regex.
# Pattern handles both singular and plural, with or without spaces.
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
        if ids:
            cited.setdefault(f"{label} (prose @ char {match.start()})", []).extend(ids)


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
# Step 2: resolve each cited id against audit_records.
# ----------------------------------------------------------------------
all_cited = sorted(
    {ref for refs in cited.values() for ref in refs}
)
resolved: dict[int, Any] = {}
dangling: list[int] = []

for ref in all_cited:
    row = events_by_id.get(ref)
    if row is None:
        dangling.append(ref)
    else:
        resolved[ref] = row

# Inverse map: for each ref, which sources cited it (for verbose output).
by_ref: dict[int, list[str]] = defaultdict(list)
for source, refs in cited.items():
    for ref in refs:
        by_ref[ref].append(source)

# Group by source row type for the summary view.
by_type: dict[str, list[int]] = defaultdict(list)
for ref, row in resolved.items():
    by_type[row.type].append(ref)

# ----------------------------------------------------------------------
# Step 3: walk the contributing specialist_finding rows -> their
# evidence_refs (one extra hop the prose sometimes skips).
# ----------------------------------------------------------------------
specialist_rows = [
    events_by_id.get(rid)
    for rid in rec_content.get("evidence_refs") or []
    if isinstance(rid, int) and events_by_id.get(rid) is not None
]
specialist_hop_refs: dict[int, list[int]] = {}
for sr in specialist_rows:
    if sr is None:
        continue
    sf_refs = sr.content.get("evidence_refs") or []
    valid = [x for x in sf_refs if isinstance(x, int)]
    specialist_hop_refs[sr.id] = valid

# ----------------------------------------------------------------------
# Step 4: print the report.
# ----------------------------------------------------------------------
print(f"=== evidence-chain verification ===")
print(f"  cycle_id     : {cycle_id}")
print(f"  application  : {app_name}")
print(f"  cycle rows   : {len(events)}")
print()
print(f"  unique refs cited      : {len(all_cited)}")
print(f"  resolved cleanly       : {len(resolved)}")
print(f"  DANGLING (unresolved)  : {len(dangling)}")
print()

print(f"=== resolved refs by source-row type ===")
for row_type in sorted(by_type.keys()):
    refs = sorted(by_type[row_type])
    print(f"  {row_type:24} {len(refs):3} refs  e.g. {refs[:5]}{'...' if len(refs) > 5 else ''}")
print()

print(f"=== specialist-finding hop (live recommendation cites these specialists) ===")
for sf_id, sf_refs in sorted(specialist_hop_refs.items()):
    sf = events_by_id[sf_id]
    print(f"  id={sf_id}  agent={sf.agent}  evidence_refs={sf_refs}")
    missing = [r for r in sf_refs if r not in events_by_id]
    if missing:
        print(f"    !! specialist cited refs not in cycle: {missing}")
print()

if verbose:
    print(f"=== every cited ref + its sources + resolved row ===")
    for ref in all_cited:
        row = resolved.get(ref)
        sources = by_ref[ref]
        if row is not None:
            extra = ""
            if row.type == "observation":
                tool = (row.content or {}).get("tool_name") or "?"
                extra = f"  tool={tool}"
            elif row.type == "specialist_finding":
                extra = f"  finding_type={(row.content or {}).get('finding_type')}"
            print(f"  ref={ref:3}  type={row.type:24} agent={row.agent}{extra}")
        else:
            print(f"  ref={ref:3}  DANGLING")
        for s in sources:
            print(f"           cited by  {s}")
        print()

if dangling:
    print(f"=== DANGLING references ===")
    for ref in dangling:
        print(f"  ref={ref}  cited by:")
        for s in by_ref[ref]:
            print(f"    - {s}")
    print()
    print("VERIFICATION FAILED — at least one cited evidence_ref does not "
          "resolve to a row in this cycle's audit_records.")
    sys.exit(1)

print("VERIFICATION PASSED — every cited evidence_ref resolves cleanly.")
PY
