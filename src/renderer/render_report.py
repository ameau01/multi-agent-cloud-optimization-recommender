"""Render a full Composite into the recommendation report markdown.

The output mirrors sample_runs/reports/scenario_NN_report.md. Sections,
in order:

  1. Title block
  2. Banner blockquote (what's real / illustrative / verifiable)
  3. Final recommendation table
  4. specific_change prose (from top-level Composite field)
  5. Summary
  6. Specialist findings table + footer
  7. Cross-tier analysis prose
  8. Trade-off analysis table + footer
  9. Evidence anchors table + footer
  10. Evaluator confidence
  11. How to verify (boilerplate-with-scenario-specific-bits)
  12. Replayability
  13. Handoff table + footer

Sections that the composite does not populate are simply omitted. A
thin composite (eval-set variant, no report_content) produces a
degenerate report: just the title block + final recommendation derived
from the top-level prediction fields + specific_change.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..models.composite import Composite, ReportContent


_SECTION_DIVIDER = "---"


# ============================================================
# Table helpers
# ============================================================
def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Render a list of dicts as a markdown table.

    Column widths are computed from the longest cell in each column so
    the rendered table is visually aligned (every body row matches the
    header / separator row width).
    """
    if not rows:
        return ""

    # Compute column widths.
    widths: dict[str, int] = {}
    for col in columns:
        widths[col] = max(len(col), *(len(str(r.get(col, ""))) for r in rows))

    def _row(values: Iterable[str]) -> str:
        return "| " + " | ".join(values) + " |"

    header = _row(col.ljust(widths[col]) for col in columns)
    # Separator uses no spaces around the dashes (matches existing style):
    # `|--------|--------|` instead of `| ------ | ------ |`.
    separator = "|" + "|".join("-" * (widths[col] + 2) for col in columns) + "|"
    body = [
        _row(str(r.get(col, "")).ljust(widths[col]) for col in columns)
        for r in rows
    ]
    return "\n".join([header, separator, *body])


def _key_value_table(rows: list[dict[str, str]]) -> str:
    """Render a 2-column {Field, Value} table from a list of
    {"field": ..., "value": ...} dicts.
    """
    return _markdown_table(
        [{"Field": r["field"], "Value": r["value"]} for r in rows],
        ["Field", "Value"],
    )


# ============================================================
# Section renderers
# ============================================================
def _title_block(rc: ReportContent | None, composite: Composite) -> str:
    name = rc.scenario_name if rc and rc.scenario_name else None
    date = rc.analysis_date if rc and rc.analysis_date else None
    status = rc.status_line if rc and rc.status_line else None

    lines = ["# Optimization Recommendation Report", ""]
    scenario_line = f"**Scenario.** {composite.scenario_id}"
    if name:
        scenario_line += f", {name}"
    lines.append(scenario_line)
    if date:
        lines.append(f"**Analysis date.** {date}")
    if status:
        lines.append(f"**Status.** {status}")
    return "\n".join(lines)


def _banner(rc: ReportContent | None) -> str | None:
    if not rc or not rc.report_banner:
        return None
    pieces = []
    for key in ("what_is_real_in_report",
                "what_is_illustrative",
                "what_is_verifiable_today"):
        text = rc.report_banner.get(key)
        if text:
            pieces.append(text)
    if not pieces:
        return None
    quoted = []
    for i, piece in enumerate(pieces):
        for line in piece.splitlines():
            quoted.append("> " + line if line else ">")
        if i < len(pieces) - 1:
            quoted.append(">")
    return "\n".join(quoted)


# Human-readable label for each action_category enum value. The raw
# enum value is the machine identity (it's what the eval-set's
# Correctness layer checks against the gold's allowed list); the label
# is the prose scope a reviewer needs to read the report without
# misinterpreting the enum's NAME as the recommendation's CONTENT.
#
# The most important entry is `query_cache_optimization` — its name
# reads as "do something with a cache layer" but its actual scope in
# this project is "fix the query layer" (indexes, query rewrites, and/
# or query caching). A live recommendation can correctly land this
# category while explicitly excluding a cache layer; without the
# label expansion a careful reviewer reads that as a self-
# contradiction.
_ACTION_CATEGORY_LABELS: dict[str, str] = {
    "query_cache_optimization":
        "query-layer fixes (indexes, query rewrites, and/or caching)",
    "cache_capacity_adjustment":
        "cache tier capacity changes (memory, node count, sharding)",
    "replica_adjustment":
        "read-replica scaling and R/W splitting",
    "pool_sizing":
        "connection-pool sizing",
    "rightsizing":
        "instance-size or fleet rightsizing",
    "scaling_policy_change":
        "auto-scaling policy and thresholds",
    "load_balancer_reconfiguration":
        "load-balancer routing or algorithm changes",
    "network_topology_change":
        "network topology or routing changes",
    "sla_review":
        "SLA target review (no infrastructure change)",
}


def _format_action_category(value: str | None) -> str:
    """Render `action_category` as raw enum + short scope clarification."""
    if not value:
        return ""
    label = _ACTION_CATEGORY_LABELS.get(value)
    if label is None:
        return f"`{value}`"
    return f"`{value}` — {label}"


def _final_recommendation(rc: ReportContent | None,
                          composite: Composite) -> str:
    if rc and rc.final_recommendation_rows:
        rows = rc.final_recommendation_rows
    else:
        # Build a default from top-level prediction fields.
        rows = [
            {"field": "Finding type", "value": f"`{composite.finding_type}`"},
        ]
        if composite.primary_tier:
            rows.append({"field": "Primary tier",
                         "value": f"`{composite.primary_tier}`"})
        if composite.secondary_tier:
            rows.append({"field": "Secondary tier",
                         "value": f"`{composite.secondary_tier}`"})
        if composite.action_category:
            rows.append({"field": "Action category",
                         "value": _format_action_category(
                             composite.action_category
                         )})

    return "## Final recommendation\n\n" + _key_value_table(rows)


def _specialist_findings(rc: ReportContent) -> str | None:
    if not rc.specialist_findings_summary:
        return None
    columns = list(rc.specialist_findings_summary[0].keys())
    table = _markdown_table(rc.specialist_findings_summary, columns)
    intro = getattr(rc, "specialist_findings_intro", None)
    if intro:
        return "## Specialist findings\n\n" + intro + "\n\n" + table
    return "## Specialist findings\n\n" + table


def _trade_off(rc: ReportContent) -> str | None:
    if not rc.trade_off_scores_table:
        return None
    columns = list(rc.trade_off_scores_table[0].keys())
    return "## Trade-off analysis\n\n" + _markdown_table(
        rc.trade_off_scores_table, columns
    )


def _evidence_anchors(rc: ReportContent) -> str | None:
    if not rc.evidence_anchors:
        return None
    columns = list(rc.evidence_anchors[0].keys())
    return "## Evidence anchors\n\n" + _markdown_table(
        rc.evidence_anchors, columns
    )


def _handoff(rc: ReportContent) -> str | None:
    if not rc.handoff:
        return None
    rows = [{"field": k, "value": str(v)} for k, v in rc.handoff.items()]
    return "## Handoff\n\n" + _key_value_table(rows)


# ============================================================
# Public entry point
# ============================================================
_MOCK_MODE_BANNER = (
    "> **MOCK MODE** — This report was rendered from a replayed audit "
    "cycle without making any live LLM calls. The reasoning, tool calls, "
    "and evidence shown below were recorded during a real prior run and "
    "are being replayed deterministically. To produce a fresh report "
    "from a live run, see [`docs/running.md`](../docs/running.md)."
)


def render_report(composite: Composite, *, mock_mode: bool = False) -> str:
    """Return the markdown report text for a composite.

    Sections present in `composite.report_content` are rendered;
    missing sections are omitted. Always finishes with a single
    trailing newline.

    Accepts either a full `Composite` (gold or sample_runs variant) or
    a bare `Recommendation` (the lenient agent-output schema, which
    doesn't carry `report_content`). For a Recommendation, all sections
    sourced from `report_content` are skipped and the output is the
    degenerate report — title block + final-recommendation table +
    `specific_change` prose. Use `getattr` so this stays a Liskov-safe
    pass-through rather than a hasattr-branch ladder.

    Args:
        composite: the source artifact.
        mock_mode: if True, a blockquote MOCK MODE banner is prepended
            above the title. Used by the hermetic demo container
            (`docker compose up demo`) so a viewer can tell the report
            came from a replayed fixture, not a fresh LLM run.
    """
    rc = getattr(composite, "report_content", None)

    sections: list[str] = []

    # 0. Mock-mode banner (when rendering replayed cycle data).
    if mock_mode:
        sections.append(_MOCK_MODE_BANNER)

    # 1. Title block + banner stay together (no divider between).
    title = _title_block(rc, composite)
    banner = _banner(rc) if rc else None
    if banner:
        sections.append(title + "\n\n" + banner)
    else:
        sections.append(title)

    # 2. Final recommendation table + specific_change prose.
    final_rec = _final_recommendation(rc, composite)
    block = final_rec + "\n\n" + composite.specific_change
    sections.append(block)

    # The following sections all come from report_content.
    if rc is None:
        return _join_sections(sections) + "\n"

    # 3. Summary
    if rc.summary:
        sections.append("## Summary\n\n" + rc.summary)

    # 4. Specialist findings
    section = _specialist_findings(rc)
    if section:
        # Allow optional trailing prose in the composite via a sibling
        # `specialist_findings_footer` field (in extra="allow" territory).
        footer = getattr(rc, "specialist_findings_footer", None)
        if footer:
            section = section + "\n\n" + footer
        sections.append(section)

    # 5. Cross-tier analysis
    if rc.cross_tier_analysis:
        sections.append("## Cross-tier analysis (Evaluator's synthesis step)\n\n"
                        + rc.cross_tier_analysis)

    # 6. Trade-off analysis
    section = _trade_off(rc)
    if section:
        footer = getattr(rc, "trade_off_footer", None)
        if footer:
            section = section + "\n\n" + footer
        sections.append(section)

    # 7. Evidence anchors
    section = _evidence_anchors(rc)
    if section:
        footer = getattr(rc, "evidence_anchors_footer", None)
        if footer:
            section = section + "\n\n" + footer
        sections.append(section)

    # 8. Evaluator confidence
    if rc.evaluator_confidence:
        sections.append("## Evaluator confidence\n\n" + rc.evaluator_confidence)

    # 9. How to verify
    if rc.how_to_verify:
        sections.append("## How to verify this report\n\n" + rc.how_to_verify)

    # 10. Replayability
    if rc.replayability:
        sections.append("## Replayability\n\n" + rc.replayability)

    # 11. Handoff
    section = _handoff(rc)
    if section:
        footer = getattr(rc, "handoff_footer", None)
        if footer:
            section = section + "\n\n" + footer
        sections.append(section)

    return _join_sections(sections) + "\n"


def _join_sections(sections: list[str]) -> str:
    """Join report sections with `---` dividers between them, except no
    divider between (How to verify) and (Replayability) — those flow as
    sibling H2s without a rule (matches the existing report style)."""
    if not sections:
        return ""
    # Detect (how_to_verify, replayability) boundary by section header text.
    out_parts: list[str] = [sections[0]]
    for prev, cur in zip(sections, sections[1:]):
        if (prev.startswith("## How to verify this report")
                and cur.startswith("## Replayability")):
            # Sibling H2s, no divider.
            out_parts.append("\n\n" + cur)
        else:
            out_parts.append("\n\n" + _SECTION_DIVIDER + "\n\n" + cur)
    return "".join(out_parts)
