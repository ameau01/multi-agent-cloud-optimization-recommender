"""Single source of truth for the eval-set's enum universes.

Every value an agent can produce for finding_type, primary_tier,
secondary_tier, or action_category must be in one of the frozensets below.
Per-scenario scoring rules (eval-set/scoring_rules/NN/rules.json) narrow
these universes to single values, but their allowed lists must contain
only values defined here.

When adding a new enum value:
  1. Add it to the appropriate frozenset below.
  2. Update docs/eval-set.md's "Enum reference" table.
  3. Update any scoring_rules/NN/rules.json files that should use it.
  4. The rules-validator test in tests/integration/ will catch drift.

NO_ACTION_FINDINGS is the sentinel set used by the short-circuit rule in
richness.py: when a prediction's finding_type is in this set, the Mid and
Rich layers bypass their per-check logic and return a single short_circuit
marker. See richness.py for the rationale.
"""

from __future__ import annotations


# ============================================================
# Enum universes
# ============================================================
FINDING_TYPES: frozenset[str | None] = frozenset({
    "issue_found",
    "no_issue_found",
    "diagnostic_deferral",
    "insufficient_data",  # Forward-compatible, not yet used in any gold
})

PRIMARY_TIERS: frozenset[str | None] = frozenset({
    "compute",
    "database",
    "cache",
    "network",
    "deferred",  # Sentinel for diagnostic_deferral scenarios
    None,
})

SECONDARY_TIERS: frozenset[str | None] = frozenset({
    "compute",
    "database",
    "cache",
    "network",
    "deferred",
    None,
})

ACTION_CATEGORIES: frozenset[str | None] = frozenset({
    "rightsizing",
    "scaling_policy_change",
    "query_cache_optimization",
    "cache_capacity_adjustment",  # Cache-specific
    "load_balancer_reconfiguration",
    "network_topology_change",
    "sla_review",
    "pool_sizing",       # Reserved; not currently in any gold
    "replica_adjustment",  # Reserved; not currently in any gold
    None,
})


# ============================================================
# Sentinel set for short-circuit rule
# ============================================================
# When a prediction's finding_type is in this set, score_mid and score_rich
# bypass their per-check logic. Rationale (hallucination prevention): when
# the right answer is "no action", asking the agent to produce keyword-rich
# prose to satisfy a Mid keyword check would invite the model to invent
# action language just to pass the check. Correctness (enum equality) is
# sufficient proof of the right answer for these findings.
NO_ACTION_FINDINGS: frozenset[str] = frozenset({
    "no_issue_found",
    "diagnostic_deferral",
    "insufficient_data",
})


# ============================================================
# Validation helper
# ============================================================
_UNIVERSES: dict[str, frozenset] = {
    "finding_type": FINDING_TYPES,
    "primary_tier": PRIMARY_TIERS,
    "secondary_tier": SECONDARY_TIERS,
    "action_category": ACTION_CATEGORIES,
}


def universe_for(field_name: str) -> frozenset:
    """Return the frozenset of allowed values for the given field name.

    Raises ValueError if the field is not a known enum field.

    Used by the rules validator (rules.py) to confirm every value in a
    rules.json file's *_allowed list is in the corresponding universe.
    """
    if field_name not in _UNIVERSES:
        raise ValueError(
            f"Unknown enum field {field_name!r}. "
            f"Known: {sorted(_UNIVERSES.keys())}"
        )
    return _UNIVERSES[field_name]


def is_valid_value(field_name: str, value) -> bool:
    """Return True if `value` is a member of the enum universe for `field_name`."""
    return value in universe_for(field_name)
