"""TierSpecialistNode — abstract base for the three tier specialists.

The specialist's run() implements one bounded ReAct loop:

  while iteration < MAX_ITERATIONS and not done:
      response = llm.complete(messages, tools=[mcp_tools, produce_finding])
      if response.tool_calls is empty:
          done; treat content as final reasoning_summary
      for tc in response.tool_calls:
          if tc.name == 'produce_finding':
              produce the structured finding, exit loop
          else:
              dispatch the tool through ActionHarness, append observation
              to messages

The Action Harness gates every tool call against the specialist's
per-agent allow-list (`src/mcp_server/scope.py`). The Reasoning
Harness gates the final produced finding (`check_finding_type` +
`check_evidence_refs_minimum`). On rejection of either, the cycle
terminates with a `failed_at_stage='specialist'` stamp via the
SpecialistError → orchestrator wrapper pattern that mirrors the
SystemMapperError → orchestrator path.

Concrete subclasses provide three things only: the agent name (drives
ActionHarness scope and audit row attribution), the human-readable
tier label (for prompt substitution), and the prompt-file name to
load. All loop mechanics live here.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ...audit.store import AuditStore
from ...harnesses.action import ActionHarness
from ...harnesses.reasoning import ReasoningHarness
from ...models.audit import AuditRecord
from ...models.enums import AgentName
from ..dispatch import dispatch_tool
from ..llm_client import LLMClient
from ..prompts import load_prompt
from ..state import CycleState


# Hard cap on ReAct iterations per specialist. A specialist that
# can't conclude in this many turns is malfunctioning; the cap
# bounds API spend and prevents runaway loops.
MAX_REACT_ITERATIONS: int = 12


# The structured-output "tool" the LLM calls to produce its final
# finding. This is not a real MCP tool — it's how Anthropic's
# tool_use protocol carries structured outputs back to the caller.
PRODUCE_FINDING_TOOL: dict[str, Any] = {
    "name": "produce_finding",
    "description": (
        "Produce your final structured finding for this tier. Call this "
        "exactly once when you have reached a conclusion. After this "
        "call, the ReAct loop terminates."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "finding_type": {
                "type": "string",
                "enum": [
                    "issue_found",
                    "no_issue_found",
                    "diagnostic_deferral",
                    "insufficient_data",
                ],
                "description": (
                    "issue_found: tier has an optimization opportunity "
                    "supported by evidence. no_issue_found: tier metrics "
                    "are healthy, no change recommended. "
                    "diagnostic_deferral: data is too thin to call. "
                    "insufficient_data: required telemetry is missing."
                ),
            },
            "headline": {
                "type": "string",
                "description": (
                    "One-sentence summary of the finding. For "
                    "no_issue_found, say what was checked; for "
                    "diagnostic_deferral, say what's missing."
                ),
            },
            "reasoning_summary": {
                "type": "string",
                "description": (
                    "2-4 sentences describing the chain of evidence "
                    "that led to this finding."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Specialist-level confidence in [0, 1]. The "
                    "Cross-Tier Evaluator separately scores its own "
                    "synthesis confidence; do not collapse the two."
                ),
            },
        },
        "required": ["finding_type", "headline", "reasoning_summary"],
    },
}


class SpecialistError(RuntimeError):
    """Raised when a specialist cannot produce a valid finding (LLM
    crashed, ReAct cap exceeded without produce_finding, Reasoning
    Harness rejected the produced finding). The orchestrator catches
    this and terminates the cycle with failed_at_stage='specialist'."""


class TierSpecialistNode(ABC):
    """Stateless functor — one instance can serve every cycle.

    Subclasses set three class attributes:
      - `agent_name`: AgentName Literal value (compute_analyst,
        data_layer_analyst, network_analyst).
      - `tier_label`: human-readable string for prompt substitution
        (e.g. "compute", "database + cache", "network").
      - `prompt_name`: filename (without .txt) in src/agents/prompts/.
    """

    agent_name: AgentName       # set by subclass
    tier_label: str             # set by subclass
    prompt_name: str            # set by subclass

    def __init__(
        self,
        store: AuditStore,
        action_harness: ActionHarness,
        reasoning_harness: ReasoningHarness,
        llm_client: LLMClient,
    ) -> None:
        self._store = store
        self._action_harness = action_harness
        self._reasoning = reasoning_harness
        self._llm = llm_client
        # Subclasses are required to set these. Catch missing values
        # early instead of crashing inside the loop.
        for attr in ("agent_name", "tier_label", "prompt_name"):
            if not getattr(type(self), attr, None):
                raise TypeError(
                    f"{type(self).__name__} must set class attribute {attr!r}"
                )

    # ----------------------------------------------------------------
    # Public entry point (called by the orchestrator graph)
    # ----------------------------------------------------------------
    def run(self, state: CycleState) -> dict[str, Any]:
        """Run the bounded ReAct loop for one cycle. Returns a state
        update dict (LangGraph reducer-friendly) plus the id of the
        specialist_finding row that landed.

        Raises SpecialistError on:
          - LLM call failures.
          - ReAct cap reached without a produce_finding call.
          - Reasoning Harness rejecting the produced finding's shape.

        Action Harness rejections of a single tool call do NOT raise;
        the dispatcher returns a ToolResult with passed=False and a
        rejection_reason, and the loop folds the rejection into the
        messages so the LLM can adjust. The harness verdict still
        lands in harness_trail either way.
        """
        finding_payload, evidence_refs = self._run_react_loop(state)
        # Validate the finding shape via the Reasoning Harness. The
        # check_finding_type rejects bad enum values; the
        # check_evidence_refs_minimum requires at least one ref when
        # finding_type='issue_found' (the other three finding_types
        # legitimately have empty evidence_refs).
        ft_check = self._reasoning.check_finding_type(
            cycle_id=state["cycle_id"],
            finding_payload=finding_payload,
            related_event_id=None,
        )
        if not ft_check.passed:
            raise SpecialistError(
                f"Reasoning Harness rejected finding_type for "
                f"{self.agent_name}: {ft_check.failure_reason}"
            )

        # evidence_refs come from the dispatch loop (observation row ids).
        finding_payload["evidence_refs"] = list(evidence_refs)
        ev_check = self._reasoning.check_evidence_refs_minimum(
            cycle_id=state["cycle_id"],
            finding_payload=finding_payload,
            related_event_id=None,
        )
        if not ev_check.passed:
            raise SpecialistError(
                f"Reasoning Harness rejected evidence binding for "
                f"{self.agent_name}: {ev_check.failure_reason}"
            )

        row_id = self._record_finding(state, finding_payload, evidence_refs)
        # Backfill both reasoning verdicts to point at the finding row.
        # Same symmetry pattern as SupervisorNode + SystemMapperNode.
        self._store.link_harness_to_event(ft_check.harness_record_id, row_id)
        self._store.link_harness_to_event(ev_check.harness_record_id, row_id)

        # Return only the DELTA (single-element lists). The reducers on
        # specialist_findings, specialist_finding_record_ids, and
        # specialists_completed (operator.add) concatenate these
        # single-element deltas across the parallel branches. Including
        # the existing list contents here would double-merge under the
        # reducer. Also: include the finding payload itself so the
        # supervisor's sort step (and the evaluator's _load_findings
        # fallback) sees the same content the audit DB sees.
        finding_with_meta = dict(finding_payload)
        finding_with_meta["specialist"] = self.agent_name
        finding_with_meta["evidence_refs"] = list(evidence_refs)
        finding_with_meta["audit_record_id"] = row_id
        return {
            "specialist_findings": [finding_with_meta],
            "specialist_finding_record_ids": [row_id],
            "specialists_completed": [self.agent_name],
        }

    # ----------------------------------------------------------------
    # ReAct loop
    # ----------------------------------------------------------------
    def _run_react_loop(
        self, state: CycleState,
    ) -> tuple[dict[str, Any], list[int]]:
        """Drive the LLM through tool-use iterations until it calls
        produce_finding (success) or hits MAX_REACT_ITERATIONS (failure).

        Returns (finding_payload_dict, evidence_refs_list). The
        finding payload comes from the produce_finding tool's arguments;
        evidence_refs is built up from each dispatched tool call's
        observation_record_id.
        """
        system_prompt = self._render_system_prompt(state)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_prompt,
                # The mock LLM keys off this for canned-response selection.
                # Real Anthropic ignores unknown keys.
                "_mock_key": (self.agent_name, "react_loop"),
            },
            {
                "role": "user",
                "content": (
                    f"Analyze the {self.tier_label} tier for "
                    f"{state['application_id']}. Run your ReAct loop, "
                    f"then call produce_finding with your conclusion."
                ),
            },
        ]

        evidence_refs: list[int] = []
        tools = self._build_tool_list()

        for iteration in range(MAX_REACT_ITERATIONS):
            response = self._llm.complete(messages, tools=tools)
            tool_calls = response.get("tool_calls") or []

            if not tool_calls:
                # Model returned plain content without invoking any tool.
                # Treat as missing produce_finding — the loop continues if
                # we have iterations left, otherwise we'll exit via the
                # cap and raise below.
                messages.append({
                    "role": "assistant",
                    "content": response.get("content") or "",
                })
                continue

            # Append the assistant turn to the message history.
            messages.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                tc_name = tc.get("name")
                tc_args = tc.get("args") or tc.get("arguments") or {}

                if tc_name == PRODUCE_FINDING_TOOL["name"]:
                    # The LLM is done. tc_args carries the finding payload.
                    finding = {
                        "specialist": self.agent_name,
                        "finding_type": tc_args.get("finding_type"),
                        "headline": tc_args.get("headline"),
                        "reasoning_summary": tc_args.get("reasoning_summary"),
                        "confidence": tc_args.get("confidence"),
                        "primary_tier": self._primary_tier_for_finding(
                            tc_args.get("finding_type")
                        ),
                    }
                    return finding, evidence_refs

                # Otherwise it's an MCP tool call. Dispatch through the
                # Action Harness (which gates by per-agent allow-list).
                result = dispatch_tool(
                    self._store,
                    self._action_harness,
                    cycle_id=state["cycle_id"],
                    agent=self.agent_name,
                    tool_name=tc_name,
                    arguments=tc_args,
                )
                if (result.passed
                        and result.observation_record_id is not None):
                    evidence_refs.append(result.observation_record_id)

                # Feed the observation (or rejection) back to the LLM
                # so it can decide what to do next.
                obs_payload = (
                    result.observation
                    if result.passed
                    else {"error": result.rejection_reason}
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id") or tc_name,
                    "content": json.dumps(obs_payload),
                })

        # Loop exited without a produce_finding call.
        raise SpecialistError(
            f"{self.agent_name} did not produce_finding within "
            f"{MAX_REACT_ITERATIONS} iterations"
        )

    # ----------------------------------------------------------------
    # Tool list — MCP tools the agent may call, plus produce_finding
    # ----------------------------------------------------------------
    def _build_tool_list(self) -> list[dict[str, Any]]:
        """Return the JSON-schema'd tool list the LLM may invoke.

        The Action Harness still gates each call at dispatch time;
        listing a tool here means the LLM *may* try to call it. The
        harness has the final say on whether the call happens.

        Per-tool schemas come from `scope.TOOL_SCHEMA_CATALOG` — the
        single source of truth that mirrors the real Python signatures
        in src/mcp_server/tools/*.py. Using the catalog (rather than a
        generic {app_name, tier?, metric?} placeholder) avoids the
        runtime TypeErrors the LLM would otherwise hit when it omits a
        required `metric`, passes `tier=` to a tool that doesn't take
        one, or invents wrong parameter names.

        If a tool appears in the allowlist but is missing from the
        catalog, falls back to the conservative "app_name only" shape
        so the call attempts something instead of crashing the loop.
        """
        from ...mcp_server import scope as scope_mod
        agent_allowlist = scope_mod.SPECIALIST_TOOL_ALLOWLIST.get(
            self.agent_name, {}
        )
        catalog = scope_mod.TOOL_SCHEMA_CATALOG
        tools: list[dict[str, Any]] = []
        for tool_name in sorted(agent_allowlist.keys()):
            allowed_tiers = agent_allowlist.get(tool_name)
            tier_note = (
                f" Allowed tier values: {allowed_tiers}."
                if allowed_tiers else ""
            )
            schema = catalog.get(tool_name) or {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
            }
            tools.append({
                "name": tool_name,
                "description": (
                    f"MCP tool {tool_name!r} scoped to "
                    f"{self.tier_label}. The Action Harness gates "
                    f"every call against the allow-list.{tier_note}"
                ),
                "input_schema": schema,
            })
        tools.append(PRODUCE_FINDING_TOOL)
        return tools

    # ----------------------------------------------------------------
    # Prompt rendering
    # ----------------------------------------------------------------
    def _render_system_prompt(self, state: CycleState) -> str:
        """Read the prompt file and substitute tier-specific context.

        The prompt files use plain {placeholder} substitution; this
        keeps the prompt-engineering surface text-only, no Jinja
        dependency. Subclasses can override if they need richer
        substitution.
        """
        template = load_prompt(self.prompt_name)
        return template.format(
            agent_name=self.agent_name,
            tier_label=self.tier_label,
            app_name=state["application_id"],
        )

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------
    @abstractmethod
    def _primary_tier_for_finding(self, finding_type: str | None) -> str | None:
        """Return the primary_tier value to stamp on the finding payload.

        Subclasses return their tier name when finding_type='issue_found',
        and None for the three non-issue finding types (matching the
        eval-set short-circuit rule). For multi-tier specialists like
        DataLayerAnalyst this returns the specialist's principal tier
        (database) rather than the secondary (cache).
        """

    def _record_finding(
        self,
        state: CycleState,
        finding_payload: dict[str, Any],
        evidence_refs: list[int],
    ) -> int:
        """Append the specialist_finding audit row, return its id.

        evidence_refs is stored both in the payload (per-finding access)
        and as a separate field for the audit-trail query layer.
        """
        record = AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="specialist_finding",
            agent=self.agent_name,
            content={
                "specialist": self.agent_name,
                "finding_type": finding_payload["finding_type"],
                "headline": finding_payload.get("headline"),
                "primary_tier": finding_payload.get("primary_tier"),
                "confidence": finding_payload.get("confidence"),
                "reasoning_summary": finding_payload.get("reasoning_summary"),
                "evidence_refs": list(evidence_refs),
            },
        )
        return self._store.add_event(record)
