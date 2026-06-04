"""Reasoning Harness — pre-produce checks on specialist findings and the
evaluator record.

What it checks today (first implementation):

  - `check_finding_type`     — finding_type is one of the three-valued
    {issue_found, no_issue_found, insufficient_data, diagnostic_deferral}
    set. The Composite Pydantic model already enforces this at parse
    time; this harness check exists so the verdict is explicit in the
    audit trail (the agent's structured output passed the three-valued
    rule) rather than implicit in "the Composite validated."
  - `check_evidence_refs_minimum` — if `finding_type == issue_found`,
    `evidence_refs` must be non-empty (otherwise the recommendation is a
    leap). Implements the evidence-sufficiency threshold from
    docs/harnesses.md §2.
  - `check_evaluator_drift_verdicts` — for an evaluator_record, every
    drift-check verdict must be one of {tight, loose, contradictory}.

What it will check in a later phase (declared, not implemented):

  - Full confidence-breakdown shape validation (every sub-signal named,
    every value in [0,1]).
  - Trade-off score completeness on evaluator records.

Each check writes a `harness_trail` row keyed by `check_name`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ..audit.schema import audit_records
from ..audit.store import AuditStore
from ..models.audit import HarnessRecord
from ..models.enums import Verdict


# Valid finding_type values (mirrors models.enums.FindingType).
_VALID_FINDING_TYPES: frozenset[str] = frozenset({
    "issue_found",
    "no_issue_found",
    "insufficient_data",
    "diagnostic_deferral",
})

# Valid drift-check verdicts per docs/harnesses.md §2a Q1-Q3.
_VALID_DRIFT_VERDICTS: frozenset[str] = frozenset({
    "tight",
    "loose",
    "contradictory",
})


@dataclass
class ReasoningCheckResult:
    """Outcome of one reasoning-harness check."""
    passed: bool
    verdict: Verdict
    check_name: str
    harness_record_id: int
    failure_reason: str | None = None


class ReasoningHarness:
    """Pre-produce structured-output checks.

    These run BEFORE a specialist's finding or the evaluator's record
    is written to `audit_records`. A failing check should cause the
    caller to either retry the agent or surface the failure to the
    Supervisor; the harness itself only records the verdict.
    """

    def __init__(self, store: AuditStore) -> None:
        self._store = store

    # ----------------------------------------------------------------
    # Three-valued finding_type
    # ----------------------------------------------------------------
    def check_finding_type(
        self,
        cycle_id: str,
        finding_payload: dict[str, Any],
        related_event_id: int | None = None,
    ) -> ReasoningCheckResult:
        """Confirm `finding_payload['finding_type']` is in the four-valued
        set. (The third element 'diagnostic_deferral' is reserved for
        scenarios where the right answer is to defer.)
        """
        check_name = "finding_type_three_valued"
        finding_type = finding_payload.get("finding_type")
        if finding_type in _VALID_FINDING_TYPES:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type="specialist_finding",
                related_event_id=related_event_id,
                verdict="passed",
                details={"finding_type": finding_type},
                failure_reason=None,
            )
        return self.route(
            cycle_id=cycle_id,
            check_name=check_name,
            target_event_type="specialist_finding",
            related_event_id=related_event_id,
            verdict="rejected",
            details={"finding_type": finding_type},
            failure_reason=(
                f"finding_type {finding_type!r} is not one of the "
                f"valid values: {sorted(_VALID_FINDING_TYPES)}."
            ),
        )

    # ----------------------------------------------------------------
    # Evidence-sufficiency threshold
    # ----------------------------------------------------------------
    def check_evidence_refs_minimum(
        self,
        cycle_id: str,
        finding_payload: dict[str, Any],
        minimum: int = 1,
        related_event_id: int | None = None,
    ) -> ReasoningCheckResult:
        """When `finding_type == issue_found`, require at least
        `minimum` entries in `evidence_refs`. Findings with non-issue
        types (no_issue_found, insufficient_data, diagnostic_deferral)
        are not subject to this check — they record an absence and
        the Composite short-circuits scoring.
        """
        check_name = "evidence_refs_minimum"
        finding_type = finding_payload.get("finding_type")
        evidence_refs = finding_payload.get("evidence_refs") or []

        # Only issue_found findings need to meet the threshold.
        if finding_type != "issue_found":
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type="specialist_finding",
                related_event_id=related_event_id,
                verdict="passed",
                details={
                    "finding_type": finding_type,
                    "evidence_refs_count": len(evidence_refs),
                    "minimum_required": minimum,
                    "applies": False,
                },
                failure_reason=None,
            )

        if len(evidence_refs) >= minimum:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type="specialist_finding",
                related_event_id=related_event_id,
                verdict="passed",
                details={
                    "finding_type": finding_type,
                    "evidence_refs_count": len(evidence_refs),
                    "minimum_required": minimum,
                },
                failure_reason=None,
            )
        return self.route(
            cycle_id=cycle_id,
            check_name=check_name,
            target_event_type="specialist_finding",
            related_event_id=related_event_id,
            verdict="rejected",
            details={
                "finding_type": finding_type,
                "evidence_refs_count": len(evidence_refs),
                "minimum_required": minimum,
            },
            failure_reason=(
                f"finding_type=issue_found requires evidence_refs of "
                f"length >= {minimum}; got {len(evidence_refs)}."
            ),
        )

    # ----------------------------------------------------------------
    # Evaluator drift-check verdicts
    # ----------------------------------------------------------------
    def check_evaluator_drift_verdicts(
        self,
        cycle_id: str,
        evaluator_payload: dict[str, Any],
        related_event_id: int | None = None,
    ) -> ReasoningCheckResult:
        """Each per-specialist drift-check verdict on an evaluator record
        must be one of {tight, loose, contradictory}. Reads the verdicts
        from `evaluator_payload['drift_verdicts']`, which is expected to
        be a dict of {specialist_name: verdict_string}.
        """
        check_name = "evaluator_drift_verdicts_valid"
        drift = evaluator_payload.get("drift_verdicts") or {}
        invalid: list[tuple[str, str]] = [
            (k, v) for k, v in drift.items()
            if v not in _VALID_DRIFT_VERDICTS
        ]
        if not invalid:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type="evaluator_record",
                related_event_id=related_event_id,
                verdict="passed",
                details={"verdict_count": len(drift)},
                failure_reason=None,
            )
        return self.route(
            cycle_id=cycle_id,
            check_name=check_name,
            target_event_type="evaluator_record",
            related_event_id=related_event_id,
            verdict="rejected",
            details={
                "verdict_count": len(drift),
                "invalid_verdicts": invalid,
            },
            failure_reason=(
                f"{len(invalid)} drift verdict(s) outside the valid "
                f"set {sorted(_VALID_DRIFT_VERDICTS)}: {invalid}."
            ),
        )

    # ----------------------------------------------------------------
    # Decision evidence-backing (Supervisor + future routers)
    # ----------------------------------------------------------------
    def check_decision_evidence_backed(
        self,
        cycle_id: str,
        decision_payload: dict[str, Any],
        related_event_id: int | None = None,
        record_type: str = "supervisor_decision",
    ) -> ReasoningCheckResult:
        """Confirm every decision is backed by evidence the cycle owns.

        Three rejection categories:
          - missing  : evidence_refs absent or empty.
          - dangling : a cited id has no audit_records row at all.
          - foreign  : a cited id exists but belongs to a different cycle.

        On pass: writes a `passed` reasoning_check row and returns
        ReasoningCheckResult(passed=True). The caller (typically the
        Supervisor) should treat a failed check as a routing block — the
        decision must not be acted on.

        Design rationale: the audit trail's "every claim traces to an
        observation" property requires every routing decision to cite
        the evidence it relied on. This check enforces that property at
        decision time, not gate time — so a decision that lacks evidence
        never gets to act.
        """
        check_name = "decision_evidence_backed"
        # The harness_trail row records the audit RecordType the decision
        # will be written as ("supervisor_decision" vs
        # "system_mapper_output"). The caller passes it explicitly so a
        # reader of harness_trail can distinguish what was verified
        # without joining audit_records. The supervisor's *decision_type*
        # ("dispatch_system_mapper" / "complete") is a sub-categorization
        # of supervisor_decision and stays in audit_records.content.
        target_event_type = record_type
        evidence_refs = decision_payload.get("evidence_refs") or []

        # Category 1: missing.
        if not evidence_refs:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type=target_event_type,
                related_event_id=related_event_id,
                verdict="rejected",
                details={
                    "decision_type": decision_payload.get("decision_type"),
                    "evidence_refs": [],
                    "rejection_category": "missing",
                },
                failure_reason=(
                    "decision has no evidence_refs; every routing decision "
                    "must cite at least one audit_records id it relied on."
                ),
            )

        # Resolve all cited ids in one query and bucket by category.
        with self._store.engine.connect() as conn:
            rows = conn.execute(
                select(audit_records.c.id, audit_records.c.cycle_id)
                .where(audit_records.c.id.in_(evidence_refs))
            ).fetchall()
        present: dict[int, str] = {int(r[0]): r[1] for r in rows}

        dangling = [rid for rid in evidence_refs if rid not in present]
        foreign = [
            rid for rid in evidence_refs
            if rid in present and present[rid] != cycle_id
        ]

        if dangling:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type=target_event_type,
                related_event_id=related_event_id,
                verdict="rejected",
                details={
                    "decision_type": decision_payload.get("decision_type"),
                    "evidence_refs": list(evidence_refs),
                    "dangling_refs": dangling,
                    "rejection_category": "dangling",
                },
                failure_reason=(
                    f"{len(dangling)} evidence_ref(s) do not resolve to any "
                    f"audit_records row: {dangling}."
                ),
            )
        if foreign:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type=target_event_type,
                related_event_id=related_event_id,
                verdict="rejected",
                details={
                    "decision_type": decision_payload.get("decision_type"),
                    "evidence_refs": list(evidence_refs),
                    "foreign_refs": foreign,
                    "rejection_category": "foreign",
                },
                failure_reason=(
                    f"{len(foreign)} evidence_ref(s) belong to a different "
                    f"cycle: {foreign}. Decisions can only cite evidence "
                    "from their own cycle."
                ),
            )

        return self.route(
            cycle_id=cycle_id,
            check_name=check_name,
            target_event_type=target_event_type,
            related_event_id=related_event_id,
            verdict="passed",
            details={
                "decision_type": decision_payload.get("decision_type"),
                "evidence_refs": list(evidence_refs),
                "verified_count": len(evidence_refs),
            },
            failure_reason=None,
        )

    # ----------------------------------------------------------------
    # Drift-check evidence density (tight verdicts must cite substance)
    # ----------------------------------------------------------------
    @staticmethod
    def _is_empty_observation(content: Any) -> bool:
        """Predicate: is this observation's body empty of measurement?

        Conservative: returns True only on clear emptiness signals so
        observations with legitimate scalar bodies (sla_target, etc.)
        don't false-positive.

        Empty signals:
          - explicit `n_records == 0` anywhere in the body
          - any top-level list field is empty (e.g.
            `per_instance_breakdown: []`, `top_queries: []`)
          - any bucket-map field is all-null (e.g.
            `by_hour_of_day: {0: None, 1: None, ...}` after a
            wrong-metric time_pattern call)
        """
        if not isinstance(content, dict):
            return False
        # Check top-level and any one-level-nested dict sub-objects.
        candidates: list[dict[str, Any]] = [content]
        for v in content.values():
            if isinstance(v, dict):
                candidates.append(v)
        for body in candidates:
            if body.get("n_records") == 0:
                return True
        # Empty list bodies (per_instance_breakdown, top_queries, etc.).
        for v in content.values():
            if isinstance(v, list) and len(v) == 0:
                return True
        # All-null bucket maps (time_pattern fallback).
        for v in content.values():
            if isinstance(v, dict):
                for bucket_key in ("by_hour_of_day", "by_weekday"):
                    buckets = v.get(bucket_key)
                    if (
                        isinstance(buckets, dict) and buckets
                        and all(x is None for x in buckets.values())
                    ):
                        return True
        return False

    def check_drift_evidence_density(
        self,
        cycle_id: str,
        evaluator_payload: dict[str, Any],
        related_event_id: int | None = None,
    ) -> ReasoningCheckResult:
        """A `tight` drift verdict must cite at least one observation
        whose body contains substantive measurement.

        Walks every drift_check row in
        `evaluator_payload['reconciliation']['drift_check']`. For each
        row with verdict='tight', looks up each `supporting_evidence_ref`
        in audit_records and applies `_is_empty_observation`. If every
        cited observation is empty, the verdict is rejected — empty
        observations cannot license tight (well-supported).

        Rationale: the audit-trail's traceability is the *first* gate,
        but a clean trace can still hide a substance failure if a
        specialist cites empty observations as if they confirmed the
        finding (e.g. compute_analyst citing `get_per_instance_breakout
        returning []` as evidence of health). This check is the
        substance-quality gate that catches that pattern mechanically.
        """
        check_name = "drift_evidence_density"
        reconciliation = evaluator_payload.get("reconciliation") or {}
        if isinstance(reconciliation, str):
            import json as _json  # noqa: PLC0415
            try:
                reconciliation = _json.loads(reconciliation)
            except _json.JSONDecodeError:
                reconciliation = {}
        drift_rows = (
            reconciliation.get("drift_check") if isinstance(reconciliation, dict)
            else []
        ) or []

        # No drift rows to check (e.g. no specialists ran) — pass through
        # rather than blocking, since there's nothing to evaluate.
        if not drift_rows:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type="evaluator_record",
                related_event_id=related_event_id,
                verdict="passed",
                details={"drift_rows_checked": 0},
                failure_reason=None,
            )

        # Pull all refs the tight rows cite, then bulk-fetch their content.
        cited_refs: set[int] = set()
        for row in drift_rows:
            if not isinstance(row, dict):
                continue
            if row.get("verdict") != "tight":
                continue
            for ref in row.get("supporting_evidence_refs") or []:
                if isinstance(ref, int):
                    cited_refs.add(ref)

        if not cited_refs:
            # No tight verdicts (or no refs cited) — vacuously passes.
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type="evaluator_record",
                related_event_id=related_event_id,
                verdict="passed",
                details={
                    "drift_rows_checked": len(drift_rows),
                    "tight_rows": 0,
                },
                failure_reason=None,
            )

        with self._store.engine.connect() as conn:
            rows = conn.execute(
                select(audit_records.c.id, audit_records.c.content)
                .where(audit_records.c.id.in_(cited_refs))
            ).fetchall()
        content_by_id: dict[int, Any] = {int(r[0]): r[1] for r in rows}

        # For each tight drift row, check whether at least one of its
        # cited observations is substantive. A tight row that cites only
        # empty observations is rejected.
        hollow_rows: list[dict[str, Any]] = []
        for row in drift_rows:
            if not isinstance(row, dict):
                continue
            if row.get("verdict") != "tight":
                continue
            refs = [r for r in (row.get("supporting_evidence_refs") or []) if isinstance(r, int)]
            if not refs:
                # tight verdict without citations — separate problem,
                # but flag here.
                hollow_rows.append({
                    "agent": row.get("agent"),
                    "refs": [],
                    "reason": "no supporting_evidence_refs",
                })
                continue
            empty_count = sum(
                1 for r in refs
                if self._is_empty_observation(content_by_id.get(r))
            )
            if empty_count == len(refs):
                hollow_rows.append({
                    "agent": row.get("agent"),
                    "refs": refs,
                    "empty_count": empty_count,
                    "reason": (
                        "every cited observation is empty (no substantive "
                        "measurement)"
                    ),
                })

        if hollow_rows:
            return self.route(
                cycle_id=cycle_id,
                check_name=check_name,
                target_event_type="evaluator_record",
                related_event_id=related_event_id,
                verdict="rejected",
                details={
                    "drift_rows_checked": len(drift_rows),
                    "hollow_tight_rows": hollow_rows,
                },
                failure_reason=(
                    f"{len(hollow_rows)} 'tight' drift verdict(s) rest on "
                    "empty observations — a tight verdict requires at "
                    "least one cited observation with substantive "
                    "measurement (n_records>0, non-empty list, or non-null "
                    "buckets)."
                ),
            )

        return self.route(
            cycle_id=cycle_id,
            check_name=check_name,
            target_event_type="evaluator_record",
            related_event_id=related_event_id,
            verdict="passed",
            details={
                "drift_rows_checked": len(drift_rows),
                "tight_rows_checked": len({
                    r.get("agent") for r in drift_rows
                    if isinstance(r, dict) and r.get("verdict") == "tight"
                }),
            },
            failure_reason=None,
        )

    # ----------------------------------------------------------------
    # Public: route a verdict through the harness
    # ----------------------------------------------------------------
    # Public on purpose. The Supervisor (and future callers) route their
    # decisions through this method so the decision lands as a
    # `harness_trail` row with a Reasoning Harness verdict attached.
    # "Route" matches the LangGraph vocabulary — moving a verdict from
    # one place to the next, as opposed to "produce" which in LangGraph
    # specifically denotes streaming Pregel events.
    def route(
        self,
        cycle_id: str,
        check_name: str,
        target_event_type: str,
        related_event_id: int | None,
        verdict: Verdict,
        details: dict[str, Any],
        failure_reason: str | None,
    ) -> ReasoningCheckResult:
        record = HarnessRecord(
            cycle_id=cycle_id,
            parent_id=None,
            related_event_id=related_event_id,
            harness="reasoning",
            type="reasoning_check",
            verdict=verdict,
            content={
                "check_name": check_name,
                "target_event_type": target_event_type,
                "details": details,
                "failure_reason": failure_reason,
            },
        )
        rid = self._store.add_harness_event(record)
        return ReasoningCheckResult(
            passed=(verdict == "passed"),
            verdict=verdict,
            check_name=check_name,
            harness_record_id=rid,
            failure_reason=failure_reason,
        )
