"""Per-tier specials (3 tools, scoped to specific specialists by scope.py).

Each tool reads from metadata.scenario_specific_evidence. The keys it
looks for are scenario-dependent: only some scenarios carry top_queries,
top_cache_keys, or per_instance_breakdown. A missing key returns an
empty list rather than raising — the agent should treat the absence as
"this scenario does not have that specific evidence."

All three tools are fully typed under the locked refactor: the response
record shapes are pinned (key_pattern/hit_count/miss_count for cache,
query_text/count/p95_latency_ms for queries, instance_id/cpu_band for
per-instance) with extra='allow' to tolerate scenario-specific fields.
"""

from __future__ import annotations

from ...models.telemetry import (
    PerInstanceBreakoutResponse,
    TopCacheKeysResponse,
    TopQueriesResponse,
)
from .._common import load_for_app
from ..server import mcp


@mcp.tool()
def get_per_instance_breakout(app_name: str) -> PerInstanceBreakoutResponse:
    """Return per-instance breakdown evidence for a Compute scenario.

    Reads from metadata.scenario_specific_evidence.per_instance_breakdown.
    Returns an empty list when the scenario has no per-instance evidence
    (true for 17 of the 18 scenarios; only scenario 05 populates it).
    """
    scenario = load_for_app(app_name)
    ev = scenario.get("metadata", {}).get("scenario_specific_evidence", {})
    return PerInstanceBreakoutResponse(
        app_name=app_name,
        per_instance_breakdown=ev.get("per_instance_breakdown", []),
    )


@mcp.tool()
def get_top_queries(app_name: str) -> TopQueriesResponse:
    """Return the top-N slowest SQL queries with counts and p95 latency.

    Reads from metadata.scenario_specific_evidence.top_queries. Returns
    an empty list when the scenario doesn't carry query evidence.
    """
    scenario = load_for_app(app_name)
    ev = scenario.get("metadata", {}).get("scenario_specific_evidence", {})
    return TopQueriesResponse(
        app_name=app_name, top_queries=ev.get("top_queries", []),
    )


@mcp.tool()
def get_top_cache_keys(app_name: str) -> TopCacheKeysResponse:
    """Return the top-N hottest cache-key patterns with hit/miss counts.

    Reads from metadata.scenario_specific_evidence.top_cache_keys.
    Returns an empty list when the scenario doesn't carry cache evidence.
    """
    scenario = load_for_app(app_name)
    ev = scenario.get("metadata", {}).get("scenario_specific_evidence", {})
    return TopCacheKeysResponse(
        app_name=app_name, top_cache_keys=ev.get("top_cache_keys", []),
    )
