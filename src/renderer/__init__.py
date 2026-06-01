"""Renderer: full Composite -> human-facing artifacts.

Two outputs per composite:
  - report.md  (markdown recommendation report, via render_report.py)
  - trace.json (audit-trail JSON, via render_trace.py)

A thin composite (eval-set variant; no trace, no report_content,
no _provenance) produces a degenerate report — title + final
recommendation + specific_change — and cannot produce a trace. A
full composite (sample_runs variant) produces both files.

Public API:
    from src.renderer import render_report, render_trace
    md   = render_report(composite)
    blob = render_trace(composite)
"""

from .render_report import render_report
from .render_trace import render_trace

__all__ = ["render_report", "render_trace"]
