"""Data Layer Analyst — tier specialist for database + cache telemetry.

Covers both tiers because they're tightly coupled in practice (cache
sits in front of the database; sizing one without the other misses
the cause/effect). The Action Harness's allow-list grants this
specialist read access to both `database` and `cache` tier telemetry.

Sets primary_tier='database' on issue_found by default; the cross-tier
evaluator may downgrade or reassign based on the cross-tier correlation
evidence.
"""

from __future__ import annotations

from .base import TierSpecialistNode


class DataLayerAnalystNode(TierSpecialistNode):
    """ReAct loop over database + cache MCP tools. One finding per cycle."""

    agent_name = "data_layer_analyst"
    tier_label = "database + cache"
    prompt_name = "data_layer_analyst"

    def _primary_tier_for_finding(self, finding_type: str | None) -> str | None:
        if finding_type == "issue_found":
            # Default to database as the principal tier; the evaluator's
            # synthesis can promote cache to primary if the cross-tier
            # evidence supports it (e.g. scenario 07 — cache-driven).
            return "database"
        return None
