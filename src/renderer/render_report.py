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

from typing import Iterable

from ..composite import Composite, ReportContent


_SECTION_DIVIDER = "---"


# ============================================================
# Table helpers
# ============================================================
def _markdown_table(rows: list[dict[str, object]], columns: list[str]) -> str:
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
                         "value": f"`{composite.action_category}`"})

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
def render_report(composite: Composite) -> str:
    """Return the markdown report text for a composite.

    Sections present in `composite.report_content` are rendered;
    missing sections are omitted. Always finishes with a single
    trailing newline.
    """
    rc = composite.report_content

    sections: list[str] = []

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
