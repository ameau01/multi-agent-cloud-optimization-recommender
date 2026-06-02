"""Shared fixtures for harness-class unit tests.

Every harness writes to the audit store, so each test gets a fresh
SQLite file under tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit import AuditStore


@pytest.fixture
def store(tmp_path: Path) -> AuditStore:
    """Fresh AuditStore on a tmp_path SQLite file. Initializes schema."""
    db_path = tmp_path / "audit.db"
    s = AuditStore(db_path=str(db_path))
    s.initialize()
    return s


@pytest.fixture
def cycle_id(store: AuditStore) -> str:
    """A started cycle for harness tests to write into."""
    return store.start_cycle(application_id="app-08", trigger_type="test")
