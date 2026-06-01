"""Render a full Composite's trace + provenance into trace.json text.

The output mirrors sample_runs/traces/scenario_NN_trace.json:
  - Top-level provenance keys first: _note, _what_is_real,
    _what_is_illustrative, _what_is_verifiable_today (each emitted only
    when present on the composite's _provenance block).
  - Then the trace blocks in fixed order: review,
    input_harness_validation, system_mapper, supervisor_decision,
    specialist_findings, evaluator_records, action_harness_gate,
    review_packet, hitl_decision (each only when present on the
    composite's trace section).
  - Single blank line separates every top-level key.
  - 2-space indent, ensure_ascii=False, trailing newline.

Returns the rendered string. The caller writes it to disk.
"""

from __future__ import annotations

import json

from ..models.composite import Composite


# Order matters: matches the existing trace.json layout.
_PROVENANCE_KEYS_AT_TOP: list[tuple[str, str]] = [
    ("note", "_note"),                                # str
    ("what_is_real", "_what_is_real"),                # list[str]
    ("what_is_illustrative", "_what_is_illustrative"),  # list[str]
    ("what_is_verifiable_today", "_what_is_verifiable_today"),  # list[str]
]

_TRACE_SECTION_KEYS: list[str] = [
    "review",
    "input_harness_validation",
    "system_mapper",
    "supervisor_decision",
    "specialist_findings",
    "evaluator_records",
    "action_harness_gate",
    "review_packet",
    "hitl_decision",
]


def render_trace(composite: Composite) -> str:
    """Return the trace.json text for a full composite.

    Raises ValueError if the composite has no trace section (a thin
    composite cannot produce a trace).
    """
    if composite.trace is None:
        raise ValueError(
            f"composite {composite.scenario_id} has no trace section; "
            f"cannot render trace.json"
        )

    sections: list[tuple[str, object]] = []

    # 1. Provenance keys at top (only those present).
    prov = composite.provenance_
    if prov is not None:
        for attr, on_disk_key in _PROVENANCE_KEYS_AT_TOP:
            value = getattr(prov, attr, None)
            if value is not None:
                sections.append((on_disk_key, value))

    # 2. Trace sections in fixed order (only those present).
    trace = composite.trace
    for key in _TRACE_SECTION_KEYS:
        value = getattr(trace, key, None)
        if value is not None:
            sections.append((key, value))

    # Serialize each top-level (key, value) pair on its own, then join
    # with blank lines and wrap in the outer object braces.
    if not sections:
        return "{}\n"

    body_lines: list[str] = []
    for i, (key, value) in enumerate(sections):
        chunk = json.dumps({key: value}, indent=2, ensure_ascii=False)
        # Strip the outermost braces from chunk; keep inner lines.
        # json.dumps with indent produces:
        #   {
        #     "key": ...
        #   }
        # We want the middle line(s) indented to match the outer object.
        inner = chunk[1:-1].rstrip("\n")  # drop leading '{' and trailing '}\n?'
        # Remove leading newline (json adds one after the opening brace)
        if inner.startswith("\n"):
            inner = inner[1:]
        # Append a trailing comma to every section except the last.
        if i < len(sections) - 1:
            body_lines.append(inner + ",")
            body_lines.append("")  # blank line between sections
        else:
            body_lines.append(inner)

    return "{\n" + "\n".join(body_lines) + "\n}\n"
