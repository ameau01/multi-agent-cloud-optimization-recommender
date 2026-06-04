"""Renderer integration test.

For each sample_runs scenario, confirm the checked-in
`sample_runs/scenario_NN/raw_recommendation.json` validates against the
Pydantic Composite schema.

Why only Pydantic validation, not byte-equality with the rendered files:

  The files under `sample_runs/reports/` and `sample_runs/traces/` are
  vendored real-run output (Opus end-to-end, 2026-06-04). Their source
  composites live in the audit DB, not on disk. The static composites
  under `sample_runs/scenario_NN/raw_recommendation.json` are kept as
  reference exemplars of the composite shape and remain valid against
  the Pydantic schema, but re-rendering them does NOT reproduce the
  vendored markdown — they are different runs.

  The byte-equality regression that used to live here was redundant with
  step 4 of `scripts/integration_test_all.sh`, which renders every live
  cycle's report.md + trace.json on every integration run. That step
  exercises the renderer against fresh composites and fails loud if the
  renderer breaks. Schema validation here is the remaining contract:
  the static exemplars stay loadable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.composite import Composite


ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_RUNS = ROOT / "sample_runs"

SCENARIO_IDS = ["02", "07", "08"]


def _composite_path(sid: str) -> Path:
    return SAMPLE_RUNS / f"scenario_{sid}" / "raw_recommendation.json"


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_composite_validates_against_pydantic(sid: str) -> None:
    Composite.model_validate_json(_composite_path(sid).read_text())
