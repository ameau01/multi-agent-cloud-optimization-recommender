"""Renderer integration test.

For each sample_runs scenario:
  1. Load the composite at sample_runs/scenario_NN/raw_recommendation.json
  2. Re-render report.md and trace.json from it
  3. Assert the rendered output equals the checked-in
     sample_runs/reports/scenario_NN_report.md and
     sample_runs/traces/scenario_NN_trace.json byte-for-byte.

This is the contract enforced by the composite refactor: the composite
is the source of truth, the rendered files are derived artifacts, and
any drift between them (the composite was edited but the renders weren't
regenerated, or vice versa) fails CI loud rather than slipping in as a
review-time miss.

To regenerate after editing a composite:
    PYTHONPATH=. python3 -m src.renderer \\
        --composite sample_runs/scenario_NN/raw_recommendation.json \\
        --out-report sample_runs/reports/scenario_NN_report.md \\
        --out-trace  sample_runs/traces/scenario_NN_trace.json
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.composite import Composite
from src.renderer import render_report, render_trace


ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_RUNS = ROOT / "sample_runs"

SCENARIO_IDS = ["02", "07", "08"]


def _composite_path(sid: str) -> Path:
    return SAMPLE_RUNS / f"scenario_{sid}" / "raw_recommendation.json"


def _report_path(sid: str) -> Path:
    return SAMPLE_RUNS / "reports" / f"scenario_{sid}_report.md"


def _trace_path(sid: str) -> Path:
    return SAMPLE_RUNS / "traces" / f"scenario_{sid}_trace.json"


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_composite_validates_against_pydantic(sid: str) -> None:
    Composite.model_validate_json(_composite_path(sid).read_text())


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_rendered_report_matches_checked_in(sid: str) -> None:
    composite = Composite.model_validate_json(_composite_path(sid).read_text())
    expected = _report_path(sid).read_text()
    actual = render_report(composite)
    assert actual == expected, (
        f"scenario {sid}: rendered report drifts from checked-in file. "
        f"Re-run scripts/build_sample_composites.py or rerun the renderer "
        f"CLI to refresh sample_runs/reports/scenario_{sid}_report.md."
    )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_rendered_trace_matches_checked_in(sid: str) -> None:
    composite = Composite.model_validate_json(_composite_path(sid).read_text())
    expected = _trace_path(sid).read_text()
    actual = render_trace(composite)
    assert actual == expected, (
        f"scenario {sid}: rendered trace drifts from checked-in file. "
        f"Re-run the renderer CLI to refresh "
        f"sample_runs/traces/scenario_{sid}_trace.json."
    )
