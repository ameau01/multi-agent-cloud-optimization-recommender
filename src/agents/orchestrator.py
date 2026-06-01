"""The orchestrate() entry point.

The function signature and contract are defined here so the rest of the
project (evaluator, tests, notebooks) can be built against a stable
interface while the agent implementations land.

When implemented, orchestrate(scenario) will:

1. Receive a scenario dict from src.data_loader.load_scenario().
2. Hand the trigger (app-name) to the Supervisor.
3. System Mapper parses Terraform, returns an analysis plan.
4. Supervisor invokes the three Tier Specialists in parallel.
5. Each specialist runs a ReAct loop, pulling telemetry via its
   tier-scoped MCP toolset (see docs/mcp-server.md).
6. Cross-Tier Evaluator drift-checks each specialist, synthesizes.
7. Action Harness gates the recommendation.
8. Returns a recommendation dict matching the eval-set/expectations/NN/raw_recommendation.json
   shape.

Until the agents are built, the function raises NotImplementedError
with a pointer to the build status. The interface itself is the first
deliverable of the agent build.
"""

from __future__ import annotations

from typing import Any


def orchestrate(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run the multi-agent pipeline on one scenario.

    Args:
        scenario: dict from `src.data_loader.load_scenario()`. Must
            contain `metadata`, `terraform`, and per-tier telemetry.

    Returns:
        A recommendation dict matching the eval-set gold-answer schema.
        Required keys: `scenario_id`, `finding_type`, `primary_tier`,
        `secondary_tier`, `action_category`, `specific_change`,
        `evidence`, `reasoning`, `projected_state`, `cost_impact`,
        `risk_assessment`. See `eval-set/expectations/NN/raw_recommendation.json` for
        worked examples.

    Raises:
        NotImplementedError: the agent system is not yet built. See
            `docs/agents.md` for the planned interface and
            `CHANGELOG.md` for status. The evaluator (`src/evaluator/`)
            is the stable interface; when this function is implemented,
            its return value will be scored by `src/evaluator/eval.py`
            without changes.
    """
    raise NotImplementedError(
        "Agent orchestration is not yet implemented (see CHANGELOG.md). "
        "The interface contract is documented in docs/agents.md. "
        "Once implemented, this function returns a recommendation dict "
        "in the shape of eval-set/expectations/NN/raw_recommendation.json, "
        "and the evaluator scores it via src/evaluator/eval.py."
    )
