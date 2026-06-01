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

import pytest

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
    """Gold-answers folder."""
    return EVAL_SET_DIR / "expectations"


@pytest.fixture(scope="session")
def evaluator_expectations_dir() -> Path:
    """Scoring-rules folder. Named for back-compat with the test code."""
    return EVAL_SET_DIR / "scoring_rules"


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
def all_gold_answers(eval_set_dir: Path) -> dict[str, dict]:
    """Load all 18 gold answers from eval-set/expectations/NN.json."""
    return {
        f"{i:02d}": json.loads((eval_set_dir / f"{i:02d}.json").read_text())
        for i in range(1, 19)
    }


@pytest.fixture(scope="session")
def all_evaluator_expectations(evaluator_expectations_dir: Path) -> dict[str, dict]:
    """Load all 18 per-scenario scoring rules."""
    return {
        f"{i:02d}": json.loads(
            (evaluator_expectations_dir / f"{i:02d}" / "rules.json").read_text()
        )
        for i in range(1, 19)
    }


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
# Judge mock fixture (Phase 7 forward-compat)
# ============================================================
@pytest.fixture
def mock_judge():
    """Return a fake LLM judge callable for Phase 7 tests.

    The fake judge reads the `_expected_judge_score` annotation from the
    prediction dict and returns it as the score. This lets tests assert
    threshold-gating behavior without an API call.

    Phase 7 will wire score_mid + score_rich to accept a judge dependency.
    This fixture matches the planned signature: judge(gold, prediction)
    returns {'score': int, 'rationale': str}.
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
