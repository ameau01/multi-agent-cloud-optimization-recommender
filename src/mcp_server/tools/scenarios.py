"""Scenario and dataset tools (5 tools).

Deliberately kept off every specialist's toolset (per scope.py). These
are for navigation, the System Mapper, the Cross-Tier Evaluator, and the
evaluator harness only.

Response models live in `src.models.telemetry`; `get_handcrafted_recommendation`
reuses the full `Composite` schema from `src.models.composite`.
"""

from __future__ import annotations

from ...models.composite import Composite
from ...models.telemetry import (
    GetCorrelationEvidenceResponse,
    GetScenarioMetadataResponse,
    GetTerraformResponse,
    ListScenariosResponse,
)
from .._common import load_for_app
from ..server import mcp


@mcp.tool()
def list_scenarios() -> ListScenariosResponse:
    """Return the catalog of app_names known to the dataset.

    Useful for external clients (Claude Desktop) to enumerate before
    asking for any specific scenario.
    """
    # Import inside the function so test stubs that monkey-patch
    # data_loader take effect. Three dots because tools/scenarios.py
    # lives at src.mcp_server.tools.scenarios; `...data_loader` walks
    # up to src.data_loader (the project's data loader).
    from ...data_loader import list_scenario_ids
    sids = list_scenario_ids()
    return ListScenariosResponse(app_names=[f"app-{sid}" for sid in sids])


@mcp.tool()
def get_scenario_metadata(app_name: str) -> GetScenarioMetadataResponse:
    """Return the full metadata document for one application.

    Includes scenario_name, scenario_type, tier_topology, business_context,
    cost_baseline, narrative, scenario_specific_evidence, and the
    before/after evidence if present. The agent reads narrower keys via
    the dedicated tools (get_business_context, get_sla_target, etc.);
    this returns the full document for clients that want everything.
    """
    scenario = load_for_app(app_name)
    return GetScenarioMetadataResponse(
        app_name=app_name, metadata=scenario.get("metadata", {}),
    )


@mcp.tool()
def get_terraform(app_name: str) -> GetTerraformResponse:
    """Return the Terraform definition for the application's infrastructure.

    Reads main.tf as raw HCL text. The System Mapper parses this to
    derive the dependency graph.
    """
    scenario = load_for_app(app_name)
    return GetTerraformResponse(
        app_name=app_name, terraform=scenario.get("terraform", ""),
    )


@mcp.tool()
def get_correlation_evidence(app_name: str) -> GetCorrelationEvidenceResponse:
    """Return the recorded cross-tier correlations for the application.

    Reads correlation_evidence.json. Used by the Cross-Tier Evaluator
    to identify cascade signatures (downstream tier leads upstream).
    Returns a list of correlation records; structure varies by scenario
    but each record typically carries tier/metric pairs plus coefficient,
    lag_minutes, and alignment_score.
    """
    scenario = load_for_app(app_name)
    raw = scenario.get("correlation_evidence", [])
    # Defensive: if the loader ever returns {} for a missing file, coerce
    # to an empty list so the response model validates cleanly.
    if isinstance(raw, dict) and not raw:
        raw = []
    return GetCorrelationEvidenceResponse(
        app_name=app_name, correlation_evidence=raw,
    )


@mcp.tool()
def get_handcrafted_recommendation(app_name: str) -> Composite:
    """Return the gold-answer recommendation for the application.

    OFF-LIMITS for every specialist (per scope.py). Available only to the
    evaluator harness, which uses it to score agent predictions. Exposing
    this on a specialist's surface would let it reason backward from the
    target, defeating the evaluation.

    Returns a full `Composite` (the same Pydantic model the renderer and
    evaluator use), so the gold answer round-trips through one schema
    end-to-end.
    """
    scenario = load_for_app(app_name)
    raw = scenario.get("handcrafted_recommendation", {})
    return Composite.model_validate(raw)
