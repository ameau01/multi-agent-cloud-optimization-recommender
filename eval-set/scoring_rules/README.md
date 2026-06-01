# scoring_rules

Per-scenario check parameters. One folder per scenario id, each holding a
single `rules.json` file.

```
scoring_rules/
├── 01/rules.json
├── 02/rules.json
├── ...
└── 18/rules.json
```

Each `rules.json` tells the evaluator what counts as the correct answer
for that scenario: the allowed values for the four enum decision fields
(`finding_type`, `primary_tier`, `secondary_tier`, `action_category`),
plus a short description and (for no-action scenarios) a `short_circuit`
flag. Open any file to see the shape; they are deliberately small and
self-describing.

The matching gold answer lives at [`../expectations/NN.json`](../expectations/).

## See also

- [`../expectations/`](../expectations/): gold answers (`NN.json`).
- [`../../docs/eval-set.md`](../../docs/eval-set.md): four-layer scoring spec, including how these rules are consumed.
- [`../../src/evaluator/rules.py`](../../src/evaluator/rules.py): loader and validator.
- [`../../src/evaluator/enums.py`](../../src/evaluator/enums.py): enum universes and `NO_ACTION_FINDINGS`.
