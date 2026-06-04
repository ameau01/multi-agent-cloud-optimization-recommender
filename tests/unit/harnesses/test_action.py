"""Tests for ActionHarness.

Covers the tool-call policy gate:
  - Allowed call for a specialist's own tier passes.
  - Cross-tier attempt by a tier specialist is rejected.
  - Out-of-allowlist tool is rejected (e.g. compute_analyst -> get_top_queries).
  - Agent not in the allow-list at all is rejected.
  - Tool that requires a tier arg but receives none is rejected.
  - Shared-context tool (no tier) passes without a tier arg.
  - cross_tier_evaluator may call telemetry on all four tiers.

Recommendation gate is declared but raises NotImplementedError (phase boundary).
"""

from __future__ import annotations

import pytest

from src.audit import AuditStore
from src.audit.queries import (
    get_harness_events_for_cycle,
    get_rejected_tool_calls_for_cycle,
)
from src.harnesses.action import ActionHarness, PolicyResult


# ============================================================
# Happy path — specialist on its own tier
# ============================================================
def test_compute_analyst_allowed_on_compute_tier(
    store: AuditStore, cycle_id: str,
) -> None:
    a = ActionHarness(store)
    result = a.check_tool_call(
        cycle_id, "compute_analyst", "get_time_series",
        {"tier": "compute", "metric": "cpu_p95"},
    )
    assert isinstance(result, PolicyResult)
    assert result.passed
    assert result.verdict == "passed"


def test_data_layer_analyst_allowed_on_database_and_cache(
    store: AuditStore, cycle_id: str,
) -> None:
    a = ActionHarness(store)
    assert a.check_tool_call(
        cycle_id, "data_layer_analyst", "get_summary_statistics",
        {"tier": "database"},
    ).passed
    assert a.check_tool_call(
        cycle_id, "data_layer_analyst", "get_summary_statistics",
        {"tier": "cache"},
    ).passed


def test_shared_context_tool_passes_without_tier_arg(
    store: AuditStore, cycle_id: str,
) -> None:
    """get_business_context and friends have no tier param; every
    specialist may call them."""
    a = ActionHarness(store)
    result = a.check_tool_call(
        cycle_id, "network_analyst", "get_business_context", {},
    )
    assert result.passed


# ============================================================
# Rejections
# ============================================================
def test_specialist_rejected_on_other_tier(
    store: AuditStore, cycle_id: str,
) -> None:
    """compute_analyst trying to read a database metric — the failure
    mode the harness exists to prevent."""
    a = ActionHarness(store)
    result = a.check_tool_call(
        cycle_id, "compute_analyst", "get_time_series",
        {"tier": "database"},
    )
    assert not result.passed
    assert result.verdict == "rejected"
    assert "database" in result.rejection_reason


def test_specialist_rejected_for_out_of_allowlist_tool(
    store: AuditStore, cycle_id: str,
) -> None:
    """compute_analyst is not in the get_top_queries allow-list at all
    — that tool is for data_layer_analyst."""
    a = ActionHarness(store)
    result = a.check_tool_call(
        cycle_id, "compute_analyst", "get_top_queries", {},
    )
    assert not result.passed
    assert "get_top_queries" in result.rejection_reason


def test_unregistered_agent_rejected_outright(
    store: AuditStore, cycle_id: str,
) -> None:
    """An agent name that isn't in SPECIALIST_TOOL_ALLOWLIST gets nothing."""
    a = ActionHarness(store)
    result = a.check_tool_call(
        cycle_id, "supervisor", "get_time_series", {"tier": "compute"},
    )
    assert not result.passed
    assert "not registered" in result.rejection_reason


def test_tier_required_but_missing(store: AuditStore, cycle_id: str) -> None:
    a = ActionHarness(store)
    result = a.check_tool_call(
        cycle_id, "compute_analyst", "get_time_series", {},
    )
    assert not result.passed
    assert "tier" in result.rejection_reason.lower()


# ============================================================
# Cross-tier evaluator: full surface
# ============================================================
@pytest.mark.parametrize("tier", ["compute", "database", "cache", "network"])
def test_cross_tier_evaluator_can_read_every_tier(
    store: AuditStore, cycle_id: str, tier: str,
) -> None:
    """The evaluator is the only specialist that may legitimately span
    all four tiers when synthesizing."""
    a = ActionHarness(store)
    result = a.check_tool_call(
        cycle_id, "cross_tier_evaluator", "get_time_series",
        {"tier": tier},
    )
    assert result.passed


# ============================================================
# Records produced
# ============================================================
def test_every_call_writes_one_harness_row(store: AuditStore, cycle_id: str) -> None:
    a = ActionHarness(store)
    a.check_tool_call(cycle_id, "compute_analyst", "get_time_series",
                      {"tier": "compute"})
    a.check_tool_call(cycle_id, "compute_analyst", "get_time_series",
                      {"tier": "database"})
    events = get_harness_events_for_cycle(store, cycle_id)
    assert len(events) == 2
    assert all(e.harness == "action" for e in events)
    assert all(e.type == "tool_call_policy_check" for e in events)


def test_rejected_calls_surface_in_dedicated_query(
    store: AuditStore, cycle_id: str,
) -> None:
    """The 'show me what the harness prevented' query returns only the
    rejected tool calls, not the passed ones — the substance-vs-
    enforcement signal."""
    a = ActionHarness(store)
    a.check_tool_call(cycle_id, "compute_analyst", "get_time_series",
                      {"tier": "compute"})        # passes
    a.check_tool_call(cycle_id, "compute_analyst", "get_top_queries",
                      {})                          # rejected
    rejs = get_rejected_tool_calls_for_cycle(store, cycle_id)
    assert len(rejs) == 1
    assert rejs[0].content["tool_name"] == "get_top_queries"


