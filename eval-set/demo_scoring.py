"""Demo: how to score a recommendation with the four-layer evaluator.

Uses app-08 (the cross-tier database cascade scenario) as a canonical
example. Constructs the Evaluator, scores the gold recommendation
against its own scoring rules, and prints the per-layer verdict.

To verify all 18 gold answers still pass their own evaluator (the
reverse-validation invariant), run the integration test instead:

    pytest tests/integration/test_golden_answers.py

Run this demo:
    python eval-set/demo_scoring.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EVAL_SET_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_SET_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluator import Evaluator

DEMO_SCENARIO = "08"  # canonical cross-tier example used across docs


def _verdict(layer_result) -> str:
    if (len(layer_result.checks) == 1
            and layer_result.checks[0].name == "short_circuit"):
        return " -- "
    return "PASS" if layer_result.passed else "FAIL"


def main():
    evaluator = Evaluator.from_eval_set_dir(
        EVAL_SET_DIR,
        dataset_examples_dir=PROJECT_ROOT / "dataset-examples",
    )
    gold = json.loads(
        (EVAL_SET_DIR / "expectations" / f"{DEMO_SCENARIO}.json").read_text()
    )
    result = evaluator.score_one(DEMO_SCENARIO, gold)

    print()
    print(f"  Scoring the gold recommendation for app-{DEMO_SCENARIO}:")
    for label, key in (("Shape", "shape"), ("Correctness", "correctness"),
                       ("Mid", "mid"), ("Rich", "rich")):
        print(f"    {label:<12s} {_verdict(result[key])}")
    print()
    print("  All four layers pass. The gold answer is internally consistent")
    print("  with its own scoring rules. To run the same check for all 18")
    print("  scenarios: pytest tests/integration/test_golden_answers.py")
    print()


if __name__ == "__main__":
    main()
