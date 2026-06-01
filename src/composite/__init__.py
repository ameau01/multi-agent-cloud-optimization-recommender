"""Composite recommendation format.

A composite bundles the gold (or live-agent) recommendation, its scoring
metadata, and (optionally) the audit trail + human-render content into
one machine-readable artifact.

The evaluator scores composites by reading the top-level prediction
fields. The renderer reads the optional trace + report_content
sections to produce markdown reports and audit-trail JSON views.

See docs/eval-set.md for the design rationale.
"""

from .schema import (
    Composite,
    ScoringMetadata,
    TraceSection,
    ReportContent,
    Provenance,
    SCHEMA_VERSION,
)

__all__ = [
    "Composite",
    "ScoringMetadata",
    "TraceSection",
    "ReportContent",
    "Provenance",
    "SCHEMA_VERSION",
]
