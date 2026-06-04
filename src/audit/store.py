"""AuditStore — the single class callers use to persist audit records.

Responsibilities:
  - Resolve the SQLite database path from AUDIT_DB_PATH env (or override),
    creating the parent directory if missing.
  - Open a SQLAlchemy engine with `PRAGMA foreign_keys = ON;` on every
    connection — SQLite does not enforce FKs by default, and the audit
    trail's "every parent reference resolves" claim depends on this.
  - Idempotently initialize the schema (CREATE TABLE IF NOT EXISTS).
  - Provide append-only insertion helpers; no update_* methods exist.
  - Encapsulate the cycle_id uniqueness invariant via start_cycle().

See `docs/audit-trail.md` for the full design.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from ..common.config import DEFAULT_AUDIT_DB_PATH, audit_db_path  # noqa: F401
from ..common.init import ensure_env_loaded
from ..models.audit import AuditRecord, HarnessRecord
from .schema import audit_records, harness_trail, metadata


# Sentinel for in-memory operation. Callers (typically tests) pass this
# to bypass all filesystem work — no dotenv lookup, no path resolution,
# no mkdir. Pairs with a StaticPool so one shared in-memory DB persists
# across the engine's connections.
IN_MEMORY = ":memory:"


def _resolve_db_path(explicit: str | None) -> Path:
    """Resolve the audit DB path.

    Delegates to `src.common.config.audit_db_path` which is the single
    source of truth for path resolution (explicit > env > default).
    When `explicit` is None, this also triggers `.env` loading once
    so the AUDIT_DB_PATH env var is visible. Tests passing an explicit
    path skip the env load entirely (no I/O).
    """
    if explicit is None:
        ensure_env_loaded()
    return audit_db_path(explicit)


def _enable_sqlite_fks(dbapi_conn, _connection_record) -> None:
    """SQLAlchemy event hook: enforce foreign keys on every SQLite
    connection. Without this, parent_id constraints are silently ignored
    and the 'every reference resolves' property of the audit trail is
    not actually enforced by the database."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def _new_cycle_id() -> str:
    """Generate a cycle_id of the form cycle_<ISO_seconds>_<8hex>.
    ~4 billion possible values per second of wall-clock — essentially
    collision-free at the rates this project ever runs."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(4)
    return f"cycle_{ts}_{suffix}"


def _row_id(result) -> int:
    """Extract the new row's integer id from a single-row INSERT result.

    SQLAlchemy types `Result.inserted_primary_key` as `Row | None`, so
    mypy can't index it directly without a narrowing check. On a
    successful single-row INSERT the value is always a non-None Row whose
    first element is the autoincrement primary key — this helper makes
    that invariant explicit and raises if the assumption is ever wrong.
    """
    pk = result.inserted_primary_key
    if pk is None:
        raise RuntimeError(
            "INSERT did not return a primary key (unexpected for an "
            "autoincrement INTEGER PRIMARY KEY)"
        )
    return int(pk[0])


# ============================================================
# AuditStore
# ============================================================
class AuditStore:
    """Append-only audit persistence backed by SQLite.

    Construct once per process. Reuse the same instance across writes
    for connection pooling. Thread-safe at the SQLAlchemy level for
    SQLite's default isolation; single-writer assumption suffices for
    this project's scale.
    """

    def __init__(self, db_path: str | None = None) -> None:
        # In-memory short-circuit. Skips dotenv, path resolution, and
        # mkdir entirely. Uses StaticPool + check_same_thread=False so
        # a single shared in-memory database lives for the engine's
        # lifetime — without that, each new connection would see its
        # own empty `:memory:` instance.
        if db_path == IN_MEMORY:
            self.db_path = Path(IN_MEMORY)
            self._engine: Engine = create_engine(
                "sqlite:///:memory:",
                future=True,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        else:
            self.db_path = _resolve_db_path(db_path)
            self._engine = create_engine(
                f"sqlite:///{self.db_path}",
                future=True,
            )
        # Register the FK-enforcement hook on every new connection.
        event.listen(self._engine, "connect", _enable_sqlite_fks)

    # --------------------------------------------------------
    # Schema lifecycle
    # --------------------------------------------------------
    def initialize(self) -> None:
        """Idempotent: create tables and indexes if they do not exist.
        Safe to call on every process start."""
        metadata.create_all(self._engine)

    # --------------------------------------------------------
    # Cycle lifecycle (audit_records table)
    # --------------------------------------------------------
    def start_cycle(
        self,
        application_id: str,
        trigger_type: str = "manual",
        scenario_hash: str | None = None,
        notes: str | None = None,
        agent: str = "supervisor",
    ) -> str:
        """Begin a new review cycle. Generates a fresh cycle_id, inserts
        the cycle_started record (parent_id=NULL), and returns the cycle_id.

        Raises sqlalchemy.exc.IntegrityError if (somehow) the cycle_id
        collides — caller can retry. Collision probability is ~0 at
        portfolio scale.
        """
        cycle_id = _new_cycle_id()
        content = {
            "application_id": application_id,
            "trigger_type": trigger_type,
            "scenario_hash": scenario_hash,
            "notes": notes,
        }
        with self._engine.begin() as conn:
            conn.execute(
                insert(audit_records).values(
                    cycle_id=cycle_id,
                    parent_id=None,
                    category="decision",
                    type="cycle_started",
                    agent=agent,
                    content=content,
                )
            )
        return cycle_id

    def get_cycle_started_id(self, cycle_id: str) -> int | None:
        """Return the audit_records.id of the cycle_started row for this
        cycle, or None if the cycle doesn't exist. Used by the Supervisor
        to cite cycle_started as evidence on its first decision (when no
        other audit_records row exists yet)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                select(audit_records.c.id).where(
                    (audit_records.c.cycle_id == cycle_id)
                    & (audit_records.c.type == "cycle_started")
                )
            ).fetchone()
        return int(row[0]) if row is not None else None

    def add_event(self, record: AuditRecord) -> int:
        """Append one event to audit_records. Returns the inserted row id.

        The record's id and timestamp fields are ignored (populated by
        SQLite); the rest of the fields are inserted as given.

        Raises pydantic.ValidationError if the record doesn't validate.
        Raises sqlalchemy.exc.IntegrityError on FK violation (bogus
        parent_id) or unique-index violation (duplicate cycle_started /
        cycle_completed for the same cycle_id).
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(audit_records).values(
                    cycle_id=record.cycle_id,
                    parent_id=record.parent_id,
                    category=record.category,
                    type=record.type,
                    agent=record.agent,
                    content=record.content,
                )
            )
            return _row_id(result)

    # --------------------------------------------------------
    # Harness trail (harness_trail table)
    # --------------------------------------------------------
    def link_harness_to_event(
        self,
        harness_record_id: int,
        audit_record_id: int,
    ) -> None:
        """Backfill harness_trail.related_event_id on an already-written
        harness row to point at the audit_records row it judged.

        This is the single shared backfill helper used by every harness
        whose check fires before the audit row exists (Reasoning at the
        Supervisor + System Mapper, Orchestration at cycle completion)
        and by the Action Harness's tool-call dispatcher (which fires
        before the tool_call row is written). Centralizing the UPDATE
        here means there is one place that breaks if the link semantics
        change, and one obvious symmetry test target.

        Idempotent: re-running with the same arguments is a no-op
        (UPDATE writes the same value back). Does not validate that
        either id exists — the FK on harness_trail.parent_id is the
        only structural constraint, and related_event_id is intentionally
        a soft reference (no FK) because some harness rows reference
        records that may not exist when the harness fires (e.g. a
        rejected reasoning check refers to a payload that was never
        written).
        """
        with self._engine.begin() as conn:
            conn.execute(
                harness_trail.update()
                .where(harness_trail.c.id == harness_record_id)
                .values(related_event_id=audit_record_id)
            )

    def add_harness_event(self, record: HarnessRecord) -> int:
        """Append one event to harness_trail. Returns the inserted row id.

        Used by the four harness modules. The record's id and timestamp
        fields are ignored (populated by SQLite); the rest are inserted
        as given.

        Raises pydantic.ValidationError if the record doesn't validate
        (e.g. unknown harness name, unknown verdict).
        Raises sqlalchemy.exc.IntegrityError if `parent_id` points to a
        nonexistent harness_trail row (PRAGMA foreign_keys=ON catches this).
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(harness_trail).values(
                    cycle_id=record.cycle_id,
                    parent_id=record.parent_id,
                    related_event_id=record.related_event_id,
                    harness=record.harness,
                    type=record.type,
                    verdict=record.verdict,
                    content=record.content,
                )
            )
            return _row_id(result)

    def complete_cycle(
        self,
        cycle_id: str,
        final_status: str = "completed",
        failure_reason: str | None = None,
        failed_at_stage: str | None = None,
        recommendation_record_id: int | None = None,
        agent: str = "supervisor",
    ) -> int:
        """Append the cycle_completed record. parent_id is set to the
        cycle_started record's id, computed via lookup.

        `failed_at_stage` is the machine-readable counterpart to the
        prose `failure_reason` — one of the FailureStage Literal values
        (see src/models/enums.py). Required when final_status != "completed";
        ignored on success.

        Raises ValueError if no cycle_started row exists for cycle_id.
        Raises IntegrityError if cycle_completed already exists for this
        cycle (caught by the one_end_per_cycle partial unique index).
        """
        with self._engine.begin() as conn:
            row = conn.execute(
                select(audit_records.c.id).where(
                    (audit_records.c.cycle_id == cycle_id)
                    & (audit_records.c.type == "cycle_started")
                )
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"No cycle_started record found for cycle_id={cycle_id!r}"
                )
            cycle_started_id = int(row[0])
            content = {
                "final_status": final_status,
                "failure_reason": failure_reason,
                "failed_at_stage": failed_at_stage,
                "recommendation_record_id": recommendation_record_id,
            }
            result = conn.execute(
                insert(audit_records).values(
                    cycle_id=cycle_id,
                    parent_id=cycle_started_id,
                    category="decision",
                    type="cycle_completed",
                    agent=agent,
                    content=content,
                )
            )
            return _row_id(result)

    # --------------------------------------------------------
    # Engine access (for queries.py and composer.py)
    # --------------------------------------------------------
    @property
    def engine(self) -> Engine:
        """Expose the underlying engine to the read-only helpers in
        queries.py and composer.py. They never write — write paths go
        through the methods above."""
        return self._engine
