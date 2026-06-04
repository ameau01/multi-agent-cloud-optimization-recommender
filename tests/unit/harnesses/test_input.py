"""Tests for InputHarness.

Covers:
  - validate_trigger accepts every published app-NN id (01..18).
  - validate_trigger rejects bogus ids (wrong prefix, out-of-range NN).
  - validate_application_known agrees with the published-set.
  - Each check produces exactly one harness_trail row with the right shape.
  - validate_bundle is declared but raises NotImplementedError (phase
    boundary; signature stable).
"""

from __future__ import annotations

import pytest

from src.audit import AuditStore
from src.audit.queries import get_harness_events_for_cycle
from src.harnesses.input import InputHarness, ValidationResult


# ============================================================
# validate_trigger
# ============================================================
def test_accepts_every_published_app_id(store: AuditStore, cycle_id: str) -> None:
    h = InputHarness(store)
    for n in range(1, 19):
        result = h.validate_trigger(cycle_id, f"app-{n:02d}")
        assert result.passed is True
        assert result.verdict == "passed"
        assert result.failure_reason is None


@pytest.mark.parametrize("bogus", [
    "app-19",     # out of range (only 01..18)
    "app-00",     # out of range (zero)
    "app-1",      # missing leading zero
    "app-008",    # extra digit
    "App-08",     # wrong case
    "app_08",     # underscore instead of hyphen
    "",           # empty
    "scenario-08",  # wrong prefix
])
def test_rejects_malformed_trigger(store: AuditStore, cycle_id: str, bogus: str) -> None:
    h = InputHarness(store)
    result = h.validate_trigger(cycle_id, bogus)
    assert result.passed is False
    assert result.verdict == "rejected"
    assert result.failure_reason is not None
    assert bogus in result.failure_reason or repr(bogus) in result.failure_reason \
        or (bogus == "" and "''" in result.failure_reason)


def test_trigger_check_writes_one_harness_row(store: AuditStore, cycle_id: str) -> None:
    h = InputHarness(store)
    h.validate_trigger(cycle_id, "app-08")
    events = get_harness_events_for_cycle(store, cycle_id)
    assert len(events) == 1
    ev = events[0]
    assert ev.harness == "input"
    assert ev.type == "input_validation"
    assert ev.verdict == "passed"
    assert ev.content["check_name"] == "trigger_legitimacy"
    assert ev.content["application_id"] == "app-08"


def test_rejection_carries_failure_reason_into_record(
    store: AuditStore, cycle_id: str,
) -> None:
    h = InputHarness(store)
    h.validate_trigger(cycle_id, "app-99")
    events = get_harness_events_for_cycle(store, cycle_id)
    rejection = next(e for e in events if e.verdict == "rejected")
    assert rejection.content["failure_reason"] is not None
    assert "app-99" in rejection.content["failure_reason"]


def test_returns_validation_result_with_harness_record_id(
    store: AuditStore, cycle_id: str,
) -> None:
    h = InputHarness(store)
    result = h.validate_trigger(cycle_id, "app-08")
    assert isinstance(result, ValidationResult)
    assert result.harness_record_id > 0
    assert result.check_name == "trigger_legitimacy"


# ============================================================
# validate_application_known
# ============================================================
def test_application_known_accepts_published_ids(
    store: AuditStore, cycle_id: str,
) -> None:
    h = InputHarness(store)
    assert h.validate_application_known(cycle_id, "app-01").passed
    assert h.validate_application_known(cycle_id, "app-18").passed


def test_application_known_rejects_unknown_ids(
    store: AuditStore, cycle_id: str,
) -> None:
    h = InputHarness(store)
    r = h.validate_application_known(cycle_id, "app-99")
    assert r.passed is False
    assert r.check_name == "application_known"


# ============================================================
# validate_bundle (phase boundary)
# ============================================================
def test_validate_bundle_signature_stable_but_unimplemented(
    store: AuditStore, cycle_id: str,
) -> None:
    """The next phase will implement bundle-level checks. The signature
    is fixed so callers can wire the harness in now."""
    h = InputHarness(store)
    with pytest.raises(NotImplementedError, match="next phase"):
        h.validate_bundle(cycle_id, {})
