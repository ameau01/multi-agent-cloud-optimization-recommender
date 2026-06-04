"""Tests for AuditStore.

Covers:
  - Cycle lifecycle (start_cycle -> add_event -> complete_cycle)
  - Append-only discipline (no update_/delete_ methods exist)
  - FK enforcement (bogus parent_id rejected under PRAGMA foreign_keys=ON)
  - Cycle_id uniqueness (partial unique index rejects duplicate cycle_started)
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.audit import AuditStore
from src.models.audit import AuditRecord


# ============================================================
# Cycle lifecycle
# ============================================================
def test_start_cycle_returns_cycle_id(store: AuditStore) -> None:
    cid = store.start_cycle(application_id="app-08", trigger_type="test")
    assert cid.startswith("cycle_")
    assert len(cid.split("_")) == 4  # cycle_<date>_<time>_<hex>


def test_add_event_inserts_and_returns_id(store: AuditStore) -> None:
    cid = store.start_cycle(application_id="app-08")
    rec = AuditRecord(
        cycle_id=cid, parent_id=1,
        category="evidence", type="tool_call", agent="compute_analyst",
        content={"tool_name": "get_summary_statistics"},
    )
    rid = store.add_event(rec)
    assert isinstance(rid, int)
    assert rid > 0


def test_complete_cycle_writes_end_tag(store: AuditStore) -> None:
    cid = store.start_cycle(application_id="app-08")
    end_id = store.complete_cycle(cid, final_status="completed")
    assert end_id > 0
    with store.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT type FROM audit_records WHERE cycle_id = :c ORDER BY id"),
            {"c": cid},
        ).fetchall()
    types = [r[0] for r in rows]
    assert types == ["cycle_started", "cycle_completed"]


def test_complete_cycle_with_unknown_cycle_raises(store: AuditStore) -> None:
    with pytest.raises(ValueError, match="No cycle_started"):
        store.complete_cycle("cycle_does_not_exist_aaaaaaaa")


# ============================================================
# Append-only discipline
# ============================================================
def test_store_exposes_no_update_or_delete_methods(store: AuditStore) -> None:
    """Audit trail is append-only by application discipline. The store
    must not expose any method that would mutate or remove records."""
    bad_method_names = [
        name for name in dir(store)
        if not name.startswith("_")
        and any(verb in name.lower() for verb in ("update", "delete", "remove"))
    ]
    assert bad_method_names == [], (
        "AuditStore exposes mutation methods which violates append-only "
        f"discipline: {bad_method_names}"
    )


# ============================================================
# FK enforcement
# ============================================================
def test_pragma_foreign_keys_is_on(store: AuditStore) -> None:
    with store.engine.connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert fk == 1


def test_bogus_parent_id_is_rejected(store: AuditStore) -> None:
    cid = store.start_cycle(application_id="app-08")
    rec = AuditRecord(
        cycle_id=cid, parent_id=999_999,  # does not exist
        category="evidence", type="tool_call", agent="compute_analyst",
        content={"tool_name": "x"},
    )
    with pytest.raises(IntegrityError):
        store.add_event(rec)


# ============================================================
# Cycle_id uniqueness
# ============================================================
def test_duplicate_cycle_started_is_rejected(store: AuditStore) -> None:
    cid = store.start_cycle(application_id="app-08")
    # Attempt to insert a second cycle_started row with the same cycle_id
    rec = AuditRecord(
        cycle_id=cid, parent_id=None,
        category="decision", type="cycle_started", agent="supervisor",
        content={"application_id": "app-08", "trigger_type": "manual"},
    )
    with pytest.raises(IntegrityError):
        store.add_event(rec)


def test_duplicate_cycle_completed_is_rejected(store: AuditStore) -> None:
    cid = store.start_cycle(application_id="app-08")
    store.complete_cycle(cid)
    with pytest.raises(IntegrityError):
        store.complete_cycle(cid)


