"""Pytest fixtures for integration tests.

Loads the 18 gold answers, the per-scenario scoring rules, the vendored
scenario metadata, and the mock predictions used by edge-case tests.
Everything stays local so integration tests run hermetically with no
Hugging Face download.
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    # Imported only for type annotations on fixture return types. The
    # runtime import happens inside `all_composites` because src/ may not
    # be on sys.path until the bottom of this file.
    from src.models.composite import Composite

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent.parent
EVAL_SET_DIR = PROJECT_ROOT / "eval-set"


# ============================================================
# Path fixtures
# ============================================================
@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def eval_set_dir() -> Path:
    """Expectations folder. Each NN/ subfolder holds a composite
    raw_recommendation.json that carries both the gold answer and the
    scoring rubric for that scenario.
    """
    return EVAL_SET_DIR / "expectations"


@pytest.fixture(scope="session")
def vendored_scenario_08_dir() -> Path:
    return PROJECT_ROOT / "dataset-examples" / "scenario_08"


@pytest.fixture(scope="session")
def mock_predictions_dir() -> Path:
    """Mock predictions used by edge-case tests."""
    return TESTS_DIR / "fixtures" / "mock_predictions"


# ============================================================
# Data fixtures
# ============================================================
@pytest.fixture(scope="session")
def all_composites(eval_set_dir: Path) -> dict[str, "Composite"]:
    """Load all 18 composites as Pydantic Composite models, keyed by sid."""
    from src.models.composite import Composite
    out: dict[str, Composite] = {}
    for i in range(1, 19):
        sid = f"{i:02d}"
        p = eval_set_dir / sid / "raw_recommendation.json"
        out[sid] = Composite.model_validate_json(p.read_text())
    return out


@pytest.fixture(scope="session")
def all_gold_answers(all_composites: dict) -> dict[str, dict]:
    """Per-scenario gold answer derived from the composite (flat dict shape
    matching the legacy eval-set/expectations/NN.json contract).
    """
    return {sid: c.to_gold_dict() for sid, c in all_composites.items()}


@pytest.fixture(scope="session")
def all_evaluator_expectations(all_composites: dict) -> dict[str, dict]:
    """Per-scenario scoring rules derived from the composite (flat dict
    shape matching the legacy scoring_rules/NN/rules.json contract).
    """
    return {sid: c.to_rules_dict() for sid, c in all_composites.items()}


@pytest.fixture(scope="session")
def scenario_08_metadata(vendored_scenario_08_dir: Path) -> dict:
    """Scenario 08 metadata (used by fixture_citation at Rich layer)."""
    return json.loads((vendored_scenario_08_dir / "metadata.json").read_text())


@pytest.fixture(scope="session")
def mock_predictions(mock_predictions_dir: Path) -> dict[str, dict]:
    """Load the 5 mock predictions used by edge-case tests.

    Each mock targets a distinct failure path under the threshold-gating
    design (see docs/eval-set.md). Keys: 'good', 'bad_correctness',
    'low_richness', 'mid_richness', 'thin_structure'.

    Each non-good mock carries an `_expected_judge_score` field that the
    mock_judge fixture below uses to simulate the LLM judge's verdict
    without an API call.
    """
    out = {}
    for name in ("good", "bad_correctness", "low_richness",
                 "mid_richness", "thin_structure"):
        path = mock_predictions_dir / f"scenario_08_{name}.json"
        out[name] = json.loads(path.read_text())
    return out


# ============================================================
# Judge mock fixture
# ============================================================
@pytest.fixture
def mock_judge():
    """Return a fake LLM judge callable for threshold-gating tests.

    The fake judge reads the `_expected_judge_score` annotation from the
    prediction dict and returns it as the score. This lets tests assert
    threshold-gating behavior without an API call.

    Matches the signature score_mid + score_rich expect:
    judge(gold, prediction) returns {'score': int, 'rationale': str}.
    """
    def _judge(gold: dict, prediction: dict) -> dict:
        score = prediction.get("_expected_judge_score", 100)
        rationale = prediction.get(
            "_judge_score_rationale",
            "fake judge: read _expected_judge_score from prediction",
        )
        return {"score": score, "rationale": rationale}
    return _judge


# ============================================================
# Make src/ importable
# ============================================================
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
