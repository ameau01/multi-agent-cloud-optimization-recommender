"""Shared context tools (4 tools, available to every specialist).

All four return slices of metadata.json. Per docs/mcp-server.md these are
the "available to every specialist, independent of tier" surface.

Response models live in `src.models.telemetry`; FastMCP introspects the
annotation and publishes an outputSchema for each tool.
"""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

from ...models.telemetry import (
    BeforeAfterEvidenceResponse,
    BusinessContextResponse,
    MonthlyCostResponse,
    SlaTarget,
    SlaTargetResponse,
)
from .._common import load_for_app
from ..server import mcp


@mcp.tool()
def get_business_context(app_name: str) -> BusinessContextResponse:
    """Return the application's criticality, description, and SLA targets.

    Reads from metadata.business_context — useful for understanding the
    blast radius of a recommendation (a tier-1 checkout service vs an
    internal analytics tool).
    """
    scenario = load_for_app(app_name)
    bc = scenario.get("metadata", {}).get("business_context")
    if bc is None:
        raise ToolError(f"unknown_metric: business_context missing from {app_name}")
    return BusinessContextResponse(app_name=app_name, business_context=bc)


@mcp.tool()
def get_sla_target(app_name: str) -> SlaTargetResponse:
    """Return the SLA target (availability + latency).

    Reads the flat sla_target_* fields out of metadata.business_context.
    Returns an all-None SlaTarget when none of the three fields are
    populated, rather than raising — the absence of SLA data is a valid
    state, symmetric with get_before_after_evidence's empty-payload
    behaviour.
    """
    scenario = load_for_app(app_name)
    bc = scenario.get("metadata", {}).get("business_context") or {}
    sla_target = SlaTarget(
        description=bc.get("sla_target_description"),
        p95_ms=bc.get("sla_target_p95_ms"),
        availability_pct=bc.get("sla_target_availability_pct"),
    )
    return SlaTargetResponse(app_name=app_name, sla_target=sla_target)


@mcp.tool()
def get_monthly_cost(app_name: str) -> MonthlyCostResponse:
    """Return the per-tier and total monthly cost baseline.

    Reads from metadata.cost_baseline.
    """
    scenario = load_for_app(app_name)
    cost = scenario.get("metadata", {}).get("cost_baseline")
    if cost is None:
        raise ToolError(f"unknown_metric: cost_baseline missing from {app_name}")
    return MonthlyCostResponse(app_name=app_name, cost_baseline=cost)


@mcp.tool()
def get_before_after_evidence(app_name: str) -> BeforeAfterEvidenceResponse:
    """Return the before/after observation of a prior config change.

    Reads from metadata.before_after_evidence. Useful when a similar
    change was already trialled and we have a measured outcome to cite.
    Returns an empty payload when the scenario has no prior evidence.
    """
    scenario = load_for_app(app_name)
    ev = scenario.get("metadata", {}).get("before_after_evidence", {}) or {}
    # model_validate so mypy sees the dict-to-BeforeAfterEvidence coercion.
    return BeforeAfterEvidenceResponse.model_validate({
        "app_name": app_name, "before_after_evidence": ev,
    })
