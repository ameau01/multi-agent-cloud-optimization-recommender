"""Unit tests for src/evaluator/rules.py.

Tests load_rules_file, load_rules_dir, validate_rules, and
is_short_circuit_scenario using tmp_path fixtures. No reads from the
real eval-set/ folder; that's covered by tests/integration/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evaluator.rules import (
    load_rules_file,
    load_rules_dir,
    validate_rules,
    is_short_circuit_scenario,
)


# ============================================================
# Helpers for building valid rules dicts in tests
# ============================================================
def _valid_minimal_rules() -> dict:
    """A minimal rules dict with all _allowed lists pointing at valid enum values."""
    return {
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute"],
        "secondary_tier_allowed": [None],
        "action_category_allowed": ["rightsizing"],
    }


# ============================================================
# load_rules_file
# ============================================================
class TestLoadRulesFile:
    def test_loads_valid_rules_file(self, tmp_path):
        rules_path = tmp_path / "rules.json"
        rules_path.write_text(json.dumps(_valid_minimal_rules()))
        loaded = load_rules_file(rules_path)
        assert loaded["finding_type_allowed"] == ["issue_found"]
        assert loaded["primary_tier_allowed"] == ["compute"]

    def test_raises_file_not_found_on_missing_path(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_rules_file(tmp_path / "nonexistent.json")

    def test_raises_value_error_on_invalid_enum_value(self, tmp_path):
        bad_rules = _valid_minimal_rules()
        bad_rules["finding_type_allowed"] = ["bogus_finding"]
        rules_path = tmp_path / "rules.json"
        rules_path.write_text(json.dumps(bad_rules))
        with pytest.raises(ValueError) as exc_info:
            load_rules_file(rules_path)
        assert "bogus_finding" in str(exc_info.value)
        assert "finding_type" in str(exc_info.value)


# ============================================================
# load_rules_dir
# ============================================================
class TestLoadRulesDir:
    def test_loads_all_subdirs_with_rules_json(self, tmp_path):
        # Create three scenario subdirs
        for sid in ("01", "02", "03"):
            sid_dir = tmp_path / sid
            sid_dir.mkdir()
            (sid_dir / "rules.json").write_text(json.dumps(_valid_minimal_rules()))
        loaded = load_rules_dir(tmp_path)
        assert set(loaded.keys()) == {"01", "02", "03"}
        for sid, rules in loaded.items():
            assert rules["finding_type_allowed"] == ["issue_found"]

    def test_raises_file_not_found_on_missing_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_rules_dir(tmp_path / "nonexistent")

    def test_raises_when_dir_has_no_rules_files(self, tmp_path):
        # Empty dir
        with pytest.raises(FileNotFoundError):
            load_rules_dir(tmp_path)

    def test_skips_subdirs_without_rules_json(self, tmp_path):
        # One subdir has rules.json, another doesn't
        (tmp_path / "01").mkdir()
        (tmp_path / "01" / "rules.json").write_text(json.dumps(_valid_minimal_rules()))
        (tmp_path / "02").mkdir()  # no rules.json
        loaded = load_rules_dir(tmp_path)
        assert set(loaded.keys()) == {"01"}


# ============================================================
# validate_rules
# ============================================================
class TestValidateRules:
    def test_accepts_valid_rules(self):
        validate_rules(_valid_minimal_rules())  # no exception

    def test_rejects_unknown_finding_type(self):
        bad = _valid_minimal_rules()
        bad["finding_type_allowed"] = ["totally_made_up"]
        with pytest.raises(ValueError) as exc_info:
            validate_rules(bad)
        assert "totally_made_up" in str(exc_info.value)

    def test_rejects_non_list_allowed_value(self):
        bad = _valid_minimal_rules()
        bad["primary_tier_allowed"] = "compute"  # string, not list
        with pytest.raises(ValueError) as exc_info:
            validate_rules(bad)
        assert "must be a list" in str(exc_info.value)

    def test_skips_validation_when_allowed_key_absent(self):
        # No _allowed keys at all -> nothing to validate, passes
        validate_rules({"description": "no allowed lists"})

    def test_includes_source_in_error_message(self):
        bad = _valid_minimal_rules()
        bad["finding_type_allowed"] = ["fake"]
        with pytest.raises(ValueError) as exc_info:
            validate_rules(bad, source="my_file.json")
        assert "my_file.json" in str(exc_info.value)


# ============================================================
# is_short_circuit_scenario
# ============================================================
class TestIsShortCircuitScenario:
    def test_true_when_short_circuit_applies_flag_is_true(self):
        rules = {"short_circuit": {"applies": True, "reason": "..."}}
        assert is_short_circuit_scenario(rules)

    def test_false_when_short_circuit_applies_flag_is_false(self):
        rules = {"short_circuit": {"applies": False}}
        assert not is_short_circuit_scenario(rules)

    def test_false_when_short_circuit_key_absent(self):
        assert not is_short_circuit_scenario({})

    def test_false_when_short_circuit_is_not_a_dict(self):
        assert not is_short_circuit_scenario({"short_circuit": "yes"})
