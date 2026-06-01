"""Basic validation tests for the 18 composites in eval-set/expectations/.

Each scenario lives in expectations/NN/raw_recommendation.json as a
composite: gold answer (top-level prediction fields) + scoring rubric
(scoring_metadata block) in a single artifact. These tests confirm the
composites are well-formed and consistent with the project's enums.
They do not score agent output; that's the job of src/evaluator/.

The enum allowed-value sets come from src.evaluator.enums (single source
of truth). If a new enum value needs to be added, add it once in enums.py
and all of these tests pick it up automatically.

Run:
    python -m pytest tests/integration/test_eval_set_data.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.composite import Composite
# Single source of truth for the enum universes. See src/evaluator/enums.py.
# - FINDING_TYPES includes 'insufficient_data' (forward-compatible; not yet
#   used in any gold), so for dataset validation we use the subset that the
#   golds actually use today.
from src.evaluator.enums import (
    FINDING_TYPES,
    PRIMARY_TIERS,
    ACTION_CATEGORIES,
)
from src.evaluator.rules import validate_rules


# tests/integration/test_eval_set_data.py -> eval-set/expectations/NN/
EVAL_SET_DIR = (
    Path(__file__).resolve().parent.parent.parent / "eval-set"
)
EXPECTATIONS_DIR = EVAL_SET_DIR / "expectations"

SCENARIO_IDS = [f"{i:02d}" for i in range(1, 19)]


def _composite_path(sid: str) -> Path:
    return EXPECTATIONS_DIR / sid / "raw_recommendation.json"


def _load_all_composites() -> dict[str, Composite]:
    return {
        sid: Composite.model_validate_json(_composite_path(sid).read_text())
        for sid in SCENARIO_IDS
    }

REQUIRED_TOP_LEVEL_FIELDS = {
    "scenario_id",
    "finding_type",
    "specific_change",
    "primary_tier",
    "secondary_tier",
    "action_category",
    "conclusion",
    "evidence",
    "reasoning",
    "projected_state",
    "cost_impact",
    "risk_assessment",
}

# The current 18 golds use a subset of the full enum universes. The
# 'insufficient_data' finding_type is reserved (forward-compatible) and
# not used by any gold; the data-validation tests check against the
# subset that the dataset actually uses.
ALLOWED_FINDING_TYPES = FINDING_TYPES - {"insufficient_data"}
ALLOWED_TIERS = PRIMARY_TIERS  # PRIMARY_TIERS and SECONDARY_TIERS are the same set
ALLOWED_ACTION_CATEGORIES = ACTION_CATEGORIES

REQUIRED_EVIDENCE_CATEGORIES = {
    "telemetry_observations",
    "infrastructure_context",
    "correlation_observations",
}


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture(scope="module")
def composites() -> dict[str, Composite]:
    return _load_all_composites()


@pytest.fixture(scope="module")
def gold_answers(composites: dict[str, Composite]) -> dict[str, dict]:
    return {sid: c.to_gold_dict() for sid, c in composites.items()}


# ============================================================
# Presence + parseability
# ============================================================
def test_all_18_composites_present():
    missing = [sid for sid in SCENARIO_IDS if not _composite_path(sid).exists()]
    assert not missing, f"missing composites: {missing}"


def test_all_composites_parse_as_json():
    for sid in SCENARIO_IDS:
        path = _composite_path(sid)
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError as e:
            pytest.fail(f"{path} does not parse as JSON: {e}")


def test_all_composites_validate_against_pydantic_schema():
    for sid in SCENARIO_IDS:
        Composite.model_validate_json(_composite_path(sid).read_text())


def test_only_NN_subfolders_in_expectations():
    found = {p.name for p in EXPECTATIONS_DIR.iterdir() if p.is_dir()}
    expected = set(SCENARIO_IDS)
    extra = found - expected
    missing = expected - found
    assert not extra, f"unexpected subfolders in expectations/: {sorted(extra)}"
    assert not missing, f"missing subfolders in expectations/: {sorted(missing)}"


# ============================================================
# Required-field presence
# ============================================================
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_all_required_top_level_fields_present(gold_answers, sid):
    gold = gold_answers[sid]
    missing = REQUIRED_TOP_LEVEL_FIELDS - set(gold.keys())
    assert not missing, f"{sid}.json missing fields: {sorted(missing)}"


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_evidence_has_three_categories(gold_answers, sid):
    gold = gold_answers[sid]
    evidence = gold.get("evidence") or {}
    missing = REQUIRED_EVIDENCE_CATEGORIES - set(evidence.keys())
    assert not missing, (
        f"{sid}.json evidence missing categories: {sorted(missing)}"
    )


# ============================================================
# Enum value checks
# ============================================================
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_scenario_id_matches_filename(gold_answers, sid):
    assert gold_answers[sid]["scenario_id"] == sid, (
        f"{sid}.json has scenario_id={gold_answers[sid]['scenario_id']}"
    )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_finding_type_is_allowed(gold_answers, sid):
    ft = gold_answers[sid]["finding_type"]
    assert ft in ALLOWED_FINDING_TYPES, (
        f"{sid}.json finding_type={ft!r} not in {sorted(ALLOWED_FINDING_TYPES)}"
    )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_primary_tier_is_allowed(gold_answers, sid):
    pt = gold_answers[sid]["primary_tier"]
    assert pt in ALLOWED_TIERS, (
        f"{sid}.json primary_tier={pt!r} not in "
        f"{sorted(t for t in ALLOWED_TIERS if t)}"
    )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_secondary_tier_is_allowed(gold_answers, sid):
    st = gold_answers[sid]["secondary_tier"]
    assert st in ALLOWED_TIERS, (
        f"{sid}.json secondary_tier={st!r} not in "
        f"{sorted(t for t in ALLOWED_TIERS if t)}"
    )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_action_category_is_allowed(gold_answers, sid):
    ac = gold_answers[sid]["action_category"]
    assert ac in ALLOWED_ACTION_CATEGORIES, (
        f"{sid}.json action_category={ac!r} not allowed"
    )


# ============================================================
# Cross-field consistency
# ============================================================
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_specific_change_is_substantive(gold_answers, sid):
    sc = gold_answers[sid].get("specific_change") or ""
    assert len(sc.strip()) >= 50, (
        f"{sid}.json specific_change too short ({len(sc.strip())} chars)"
    )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_no_issue_found_has_null_primary_tier(gold_answers, sid):
    gold = gold_answers[sid]
    if gold["finding_type"] == "no_issue_found":
        assert gold["primary_tier"] is None, (
            f"{sid}.json finding_type=no_issue_found but "
            f"primary_tier={gold['primary_tier']}"
        )
        assert gold["action_category"] is None, (
            f"{sid}.json finding_type=no_issue_found but "
            f"action_category={gold['action_category']}"
        )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_diagnostic_deferral_has_null_action_category(gold_answers, sid):
    gold = gold_answers[sid]
    if gold["finding_type"] == "diagnostic_deferral":
        assert gold["action_category"] is None, (
            f"{sid}.json finding_type=diagnostic_deferral but "
            f"action_category={gold['action_category']}"
        )


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_issue_found_has_concrete_recommendation(gold_answers, sid):
    gold = gold_answers[sid]
    if gold["finding_type"] == "issue_found":
        assert gold["primary_tier"] is not None, (
            f"{sid}.json finding_type=issue_found requires primary_tier"
        )
        assert gold["action_category"] is not None, (
            f"{sid}.json finding_type=issue_found requires action_category"
        )


# ============================================================
# Coverage tests (the eval set as a whole)
# ============================================================
def test_all_three_finding_types_represented(gold_answers):
    seen = {g["finding_type"] for g in gold_answers.values()}
    assert seen == ALLOWED_FINDING_TYPES, (
        f"finding_type coverage incomplete: have {seen}, "
        f"want {ALLOWED_FINDING_TYPES}"
    )


def test_all_four_tiers_represented_as_primary(gold_answers):
    # Exclude the 'deferred' sentinel (used for diagnostic_deferral scenarios)
    # from the coverage check, which is about the four real cloud tiers.
    seen = {
        g["primary_tier"] for g in gold_answers.values()
        if g["primary_tier"] and g["primary_tier"] != "deferred"
    }
    expected = {"compute", "database", "cache", "network"}
    assert seen == expected, (
        f"primary_tier coverage incomplete: have {seen}, want {expected}"
    )


def test_multiple_action_categories_represented(gold_answers):
    seen = {g["action_category"] for g in gold_answers.values()
            if g["action_category"]}
    # Expect at least 6 distinct categories (rightsizing, scaling_policy_change,
    # query_cache_optimization, pool_sizing, load_balancer_reconfiguration,
    # network_topology_change)
    assert len(seen) >= 6, (
        f"action_category coverage too narrow: only {seen}"
    )


# ============================================================
# Scoring rules validation
# (Folds in what feasibility.py previously did as a standalone script.)
# ============================================================
class TestScoringRulesValidation:
    """Validate that every per-scenario rules.json is consistent with
    the enum universes defined in src.evaluator.enums.

    This catches drift between rules.json files and the enum source of
    truth at CI time. Previously this kind of check lived in the
    standalone feasibility.py script; folding it into pytest makes it
    automatic on every test run.
    """

    def test_all_composite_rules_load_and_validate(self):
        """Every composite's scoring_metadata must yield a rules dict whose
        *_allowed lists all sit within the corresponding enum universe.

        validate_rules() raises ValueError on the first mismatch; if any
        scenario has drifted, this test fails loud with the bad value
        and the source composite path.
        """
        composites = _load_all_composites()
        assert len(composites) == 18, (
            f"Expected 18 composites, found {len(composites)}"
        )
        for sid, c in composites.items():
            validate_rules(c.to_rules_dict(), source=str(_composite_path(sid)))

    def test_no_undocumented_broad_allowed_lists(self):
        """Per-scenario allowed lists should be single-value (strict equality).
        If any are broader, the composite must carry an explanatory
        _rationale field documenting why.

        Replaces the BROAD-flag detection previously done by
        src/evaluator/feasibility.py.
        """
        composites = _load_all_composites()
        undocumented_broad = []
        for sid, c in composites.items():
            rules = c.to_rules_dict()
            has_rationale = any(k.endswith("_rationale") for k in rules.keys())
            for field in ("finding_type_allowed", "primary_tier_allowed",
                          "secondary_tier_allowed", "action_category_allowed"):
                allowed = rules.get(field, [])
                if isinstance(allowed, list) and len(allowed) > 1:
                    if not has_rationale:
                        undocumented_broad.append((sid, field, allowed))
        assert not undocumented_broad, (
            f"Found broad allowed lists without _rationale documentation: "
            f"{undocumented_broad}. Either tighten to single-value or add "
            f"a rationale field to the composite's scoring_metadata block."
        )

    def test_no_action_scenarios_omit_keyword_groups(self):
        """Short-circuited scenarios (06, 15, 17) should not define
        action_keyword_groups or multi_tier_evidence, since Mid + Rich
        are bypassed. Defining them would be dead config.

        These keys aren't part of the Pydantic ScoringMetadata schema, so
        this test is now a stronger statement: composites whose scoring
        rubric is short-circuited must not even mention those keys.
        """
        composites = _load_all_composites()
        for sid, c in composites.items():
            rules = c.to_rules_dict()
            sc = rules.get("short_circuit", {})
            if isinstance(sc, dict) and sc.get("applies"):
                assert "action_keyword_groups" not in rules, (
                    f"scenario {sid}: short-circuit applies; "
                    f"action_keyword_groups is dead config, remove it"
                )
                assert "multi_tier_evidence" not in rules, (
                    f"scenario {sid}: short-circuit applies; "
                    f"multi_tier_evidence is dead config, remove it"
                )
