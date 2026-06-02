"""Reasoning Harness — pre-emit checks on specialist findings and the
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
    """Pre-emit structured-output checks.

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
        review_cycle_id: str,
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
            return self._emit(
                review_cycle_id=review_cycle_id,
                check_name=check_name,
                target_event_type="specialist_finding",
                related_event_id=related_event_id,
                verdict="passed",
                details={"finding_type": finding_type},
                failure_reason=None,
            )
        return self._emit(
            review_cycle_id=review_cycle_id,
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
        review_cycle_id: str,
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
            return self._emit(
                review_cycle_id=review_cycle_id,
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
            return self._emit(
                review_cycle_id=review_cycle_id,
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
        return self._emit(
            review_cycle_id=review_cycle_id,
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
        review_cycle_id: str,
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
            return self._emit(
                review_cycle_id=review_cycle_id,
                check_name=check_name,
                target_event_type="evaluator_record",
                related_event_id=related_event_id,
                verdict="passed",
                details={"verdict_count": len(drift)},
                failure_reason=None,
            )
        return self._emit(
            review_cycle_id=review_cycle_id,
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
    # Internal: emit and return
    # ----------------------------------------------------------------
    def _emit(
        self,
        review_cycle_id: str,
        check_name: str,
        target_event_type: str,
        related_event_id: int | None,
        verdict: Verdict,
        details: dict[str, Any],
        failure_reason: str | None,
    ) -> ReasoningCheckResult:
        record = HarnessRecord(
            review_cycle_id=review_cycle_id,
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
