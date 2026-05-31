# eval-set

The benchmark dataset. Pure data: 18 gold answers, 18 per-scenario scoring
rules, and one demo script that shows how the evaluator scores a single
recommendation. No tests live here; tests live in [`tests/`](../tests/).

For the four-layer evaluator that scores predictions against this data,
see [`docs/eval-set.md`](../docs/eval-set.md).

## What's here

```
eval-set/
├── expectations/                    18 gold answers (NN.json)
├── scoring_rules/                   18 per-scenario check parameters (NN/rules.json)
├── demo_scoring.py                  scores one gold (app-08) as a usage example
└── README.md                        (this file)
```

The 18 `expectations/NN.json` files are byte-identical copies of the
hand-crafted recommendations from
[`ameau01/synthesized-cloud-optimization-recommendations`](https://huggingface.co/datasets/ameau01/synthesized-cloud-optimization-recommendations).

## How the pieces fit

| Folder/file                                | Role                                                |
|--------------------------------------------|-----------------------------------------------------|
| `eval-set/expectations/NN.json`            | Gold answer. What the right recommendation is.      |
| `eval-set/scoring_rules/NN/rules.json`     | Per-scenario rules. What counts as a match.         |
| `src/evaluator/`                           | Pure scoring code. Reads gold + rules from here.    |
| `src/evaluator/eval.py`                    | CLI entry point (`--app-name`, `--prediction`).      |
| `src/evaluator/evaluator.py`               | `Evaluator` class for Python API use.               |
| `tests/integration/test_golden_answers.py` | Pytest: every gold passes every layer.              |
| `tests/integration/test_edge_cases.py`     | Pytest: bad mocks fail the expected layer.          |

`src/evaluator/` is pure Python with no data files. `eval-set/` is pure
data. The dependency runs one way: `src/evaluator/` reads from
`eval-set/`, never the reverse.

## App-name convention

User-facing entry points (CLI, MCP server) refer to scenarios as
`app-NN` (e.g. `app-08`) rather than bare scenario ids. This matches
the project's mental model: an alert fires against a named application;
the agent pulls telemetry for that application; the evaluator scores
the resulting recommendation for that application. The mapping `app-NN
→ scenario id NN` is the only indirection.

The Python library API (`Evaluator` class) operates at the
dataset-internal level and uses `scenario_id`; the translation happens
at the CLI surface.

## Four ways to use this folder

### 1. As reference

Open any `expectations/NN.json` to see what a complete, well-formed
recommendation looks like for that scenario.

### 2. Score one prediction (CLI)

```bash
python -m src.evaluator.eval --app-name app-08 --prediction my_prediction.json
```

Output: per-layer verdict (Shape / Correctness / Mid / Rich) + a
one-line summary. Exit codes: 0 if all layers pass, 1 if any layer
fails, 2 on usage error (missing file, malformed JSON, unknown app).

### 3. Score programmatically (Python API)

```python
import json
from pathlib import Path
from src.evaluator import Evaluator

# Build once, score many
e = Evaluator.from_eval_set_dir(
    "eval-set/",
    dataset_examples_dir="dataset-examples/",
)

prediction = json.loads(Path("my_prediction.json").read_text())
result = e.score_one("08", prediction)

print(result["shape"].passed)        # bool
print(result["correctness"].passed)  # bool
# Mid + Rich are TierResult when scored, the string "skipped" when gated.
```

The Evaluator caches rules at init; subsequent `score_one` calls are
in-memory dict lookups.

### 4. Run the demo (see the evaluator on one scenario)

```bash
python eval-set/demo_scoring.py
# or
scripts/run_demo.sh
```

Output: scores the gold for `app-08` and prints the four-layer table.
This is a usage example for a human reviewer.

To verify all 18 gold answers still pass their own evaluator, run the
integration test instead (next section).

## How to verify

Two levels of verification, depending on what you want to check.

### Verify one scenario via the CLI

```bash
# Score the gold for app-08 against its own rules.
python -m src.evaluator.eval \
    --app-name app-08 \
    --prediction eval-set/expectations/08.json
```

Expected: exit code 0, "All layers passed." on stdout.

Pick a different `app-NN` (between `app-01` and `app-18`) and a
matching `expectations/NN.json` to verify a different scenario.

### Verify all 18 scenarios via pytest

```bash
# Headline benchmark-integrity test: every gold passes every layer.
python -m pytest tests/integration/test_golden_answers.py -v

# Or via the wrapper script:
scripts/run_golden.sh -v
```

Expected: 94 tests pass (covering Shape, Correctness, Mid, Rich, and
short-circuit semantics across all 18 scenarios with both metadata-loaded
and metadata-omitted paths).

If anything fails here, the gold answers and the scoring rules have
drifted apart. Fix one or the other before publishing.

### Verify everything (data + behavior)

```bash
# Full integration suite: data validation + scorer behavior + edge cases + CLI.
python -m pytest tests/integration/ -v

# Or:
scripts/run_integration.sh -v
```

Expected: 326+ tests pass.

## Coverage at a glance

| Finding type           | Scenarios                                              | Count |
|------------------------|--------------------------------------------------------|-------|
| `issue_found`          | 01, 02, 03, 04, 05, 07, 08, 09, 10, 11, 12, 13, 14, 16, 18 | 15    |
| `no_issue_found`       | 06                                                     | 1     |
| `diagnostic_deferral`  | 15, 17                                                 | 2     |

| Primary tier   | Scenarios                              | Count |
|----------------|----------------------------------------|-------|
| `compute`      | 01, 02, 09, 11, 13, 14, 16, 18         | 8     |
| `database`     | 03, 04, 08, 12                         | 4     |
| `cache`        | 07                                     | 1     |
| `network`      | 05, 10                                 | 2     |
| `deferred`     | 15, 17                                 | 2     |
| `null`         | 06                                     | 1     |

## Provenance

The 18 gold answers + scoring rules diverge from the published Hugging
Face dataset as of Phase 6.6 (strict enum equality, new `deferred` and
`cache_capacity_adjustment` values, short-circuit rule for no-action
findings). The local copies are the source of truth; the published HF
dataset is one revision behind. Re-publication is a separate task.

## License

MIT. See the project root `LICENSE`.
