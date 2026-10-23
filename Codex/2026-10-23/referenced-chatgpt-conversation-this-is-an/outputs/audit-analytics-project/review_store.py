"""SQLite/PostgreSQL storage for auditor review records and saved versions."""
from __future__ import annotations

import csv
import io
import os
import sqlite3
import threading
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse

REVIEW_STATUSES = ("Not reviewed", "Under review", "Reviewed", "Escalated")
REVIEW_FIELDS = (
    "review_id", "transaction_id", "reviewer_identity", "review_status",
    "evidence_examined", "review_conclusion", "follow_up_action", "created_at", "updated_at",
)
HISTORY_FIELDS = (
    "history_id", "review_id", "transaction_id", "reviewer_identity",
    "previous_review_status", "review_status", "evidence_examined",
    "review_conclusion", "follow_up_action", "changed_at",
)
FINAL_STATUSES = {"Reviewed", "Escalated"}
MAX_REVIEWER_IDENTITY_LENGTH = 100

_POSTGRES_POOLS: dict[str, object] = {}
_POSTGRES_POOL_LOCK = threading.Lock()


class ReviewValidationError(ValueError):
    """Raised when review documentation is incomplete or invalid."""


class ReviewStoreError(RuntimeError):
    """Raised when review storage cannot safely complete an operation."""


class ReviewMigrationError(RuntimeError):
    """Raised when migration would conflict with data already in PostgreSQL."""


def default_database_path() -> str | Path:
    """Return the configured PostgreSQL URL or the local SQLite database path.

    Secrets can be supplied directly to store functions by the Streamlit app.
    This function intentionally reads only environment variables so importing
    the storage module does not require Streamlit's runtime.
    """
    remote = os.environ.get("AUDIT_REVIEW_DATABASE_URL", "").strip()
    if remote:
        return remote
    configured = os.environ.get("AUDIT_REVIEW_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).parent / "data" / "review_records.sqlite3"


def _is_postgres_target(target: str | Path | None) -> bool:
    return isinstance(target, str) and target.lower().startswith(("postgres://", "postgresql://"))


def validate_postgres_url(database_url: str) -> str:
    """Validate URL shape and require TLS without echoing credentials in errors."""
    try:
        parsed = urlparse(database_url)
        sslmode = parse_qs(parsed.query).get("sslmode", [""])[0].lower()
    except Exception:
        parsed, sslmode = None, ""
    if (
        parsed is None
        or parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or not parsed.path.strip("/")
    ):
        raise ReviewStoreError(
            "The configured review database URL is invalid. Use the PostgreSQL URL from your provider."
        )
    if sslmode not in {"require", "verify-ca", "verify-full"}:
        raise ReviewStoreError(
            "The configured PostgreSQL URL must enable TLS with sslmode=require or stronger."
        )
    return database_url


def _postgres_pool(database_url: str):
    """Return a small process-wide pool; the connection URL stays out of logs/UI."""
    validate_postgres_url(database_url)
    with _POSTGRES_POOL_LOCK:
        pool = _POSTGRES_POOLS.get(database_url)
        if pool is not None:
            return pool
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                conninfo=database_url,
                min_size=1,
                max_size=4,
                timeout=10,
                kwargs={"row_factory": dict_row},
                open=True,
            )
        except Exception:
            raise ReviewStoreError(
                "Could not connect to the configured review database. Check its secret, network access, and provider status."
            ) from None
        _POSTGRES_POOLS[database_url] = pool
        return pool


def _execute(connection, statement: str, parameters=()):
    """Execute shared SQL using the placeholder style required by its driver."""
    if isinstance(connection, sqlite3.Connection):
        return connection.execute(statement, parameters)
    return connection.execute(statement.replace("?", "%s"), parameters)


def _ensure_sqlite_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_records (
            transaction_id TEXT PRIMARY KEY,
            review_status TEXT NOT NULL CHECK (
                review_status IN ('Not reviewed', 'Under review', 'Reviewed', 'Escalated')
            ),
            evidence_examined TEXT NOT NULL DEFAULT '',
            review_conclusion TEXT NOT NULL DEFAULT '',
            follow_up_action TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            review_id TEXT,
            reviewer_identity TEXT NOT NULL DEFAULT ''
        )
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(review_records)")}
    if "review_id" not in columns:
        connection.execute("ALTER TABLE review_records ADD COLUMN review_id TEXT")
    if "reviewer_identity" not in columns:
        connection.execute(
            "ALTER TABLE review_records ADD COLUMN reviewer_identity TEXT NOT NULL DEFAULT ''"
        )
    rows_without_id = connection.execute(
        "SELECT transaction_id FROM review_records WHERE review_id IS NULL OR review_id = ''"
    ).fetchall()
    for row in rows_without_id:
        connection.execute(
            "UPDATE review_records SET review_id = ? WHERE transaction_id = ?",
            (str(uuid.uuid4()), row["transaction_id"]),
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_review_records_review_id ON review_records(review_id)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS review_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            reviewer_identity TEXT NOT NULL,
            previous_review_status TEXT,
            review_status TEXT NOT NULL,
            evidence_examined TEXT NOT NULL,
            review_conclusion TEXT NOT NULL,
            follow_up_action TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            FOREIGN KEY(review_id) REFERENCES review_records(review_id)
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_history_transaction ON review_history(transaction_id, history_id)"
    )
    # A one-time baseline keeps the last version of legacy records before their next update.
    connection.execute(
        """
        INSERT INTO review_history (
            review_id, transaction_id, reviewer_identity, previous_review_status,
            review_status, evidence_examined, review_conclusion, follow_up_action, changed_at
        )
        SELECT r.review_id, r.transaction_id, r.reviewer_identity, NULL,
               r.review_status, r.evidence_examined, r.review_conclusion,
               r.follow_up_action, r.updated_at
        FROM review_records AS r
        WHERE NOT EXISTS (
            SELECT 1 FROM review_history AS h WHERE h.review_id = r.review_id
        )
        """
    )


def _ensure_postgres_schema(connection) -> None:
    """Create or extend the same records/history schema on managed PostgreSQL."""
    _execute(connection, """
        CREATE TABLE IF NOT EXISTS review_records (
            transaction_id TEXT PRIMARY KEY,
            review_status TEXT NOT NULL CHECK (
                review_status IN ('Not reviewed', 'Under review', 'Reviewed', 'Escalated')
            ),
            evidence_examined TEXT NOT NULL DEFAULT '',
            review_conclusion TEXT NOT NULL DEFAULT '',
            follow_up_action TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            review_id TEXT,
            reviewer_identity TEXT NOT NULL DEFAULT ''
        )
    """)
    _execute(connection, "ALTER TABLE review_records ADD COLUMN IF NOT EXISTS review_id TEXT")
    _execute(connection, "ALTER TABLE review_records ADD COLUMN IF NOT EXISTS reviewer_identity TEXT NOT NULL DEFAULT ''")
    rows_without_id = _execute(
        connection,
        "SELECT transaction_id FROM review_records WHERE review_id IS NULL OR review_id = ''",
    ).fetchall()
    for row in rows_without_id:
        _execute(connection, "UPDATE review_records SET review_id = ? WHERE transaction_id = ?",
                 (str(uuid.uuid4()), row["transaction_id"]))
    _execute(connection, "CREATE UNIQUE INDEX IF NOT EXISTS idx_review_records_review_id ON review_records(review_id)")
    _execute(connection, """
        CREATE TABLE IF NOT EXISTS review_history (
            history_id BIGSERIAL PRIMARY KEY,
            review_id TEXT NOT NULL REFERENCES review_records(review_id),
            transaction_id TEXT NOT NULL,
            reviewer_identity TEXT NOT NULL,
            previous_review_status TEXT,
            review_status TEXT NOT NULL,
            evidence_examined TEXT NOT NULL,
            review_conclusion TEXT NOT NULL,
            follow_up_action TEXT NOT NULL,
            changed_at TEXT NOT NULL
        )
    """)
    _execute(connection, "CREATE INDEX IF NOT EXISTS idx_review_history_transaction ON review_history(transaction_id, history_id)")
    _execute(connection, """
        INSERT INTO review_history (
            review_id, transaction_id, reviewer_identity, previous_review_status,
            review_status, evidence_examined, review_conclusion, follow_up_action, changed_at
        )
        SELECT r.review_id, r.transaction_id, r.reviewer_identity, NULL,
               r.review_status, r.evidence_examined, r.review_conclusion,
               r.follow_up_action, r.updated_at
        FROM review_records AS r
        WHERE NOT EXISTS (
            SELECT 1 FROM review_history AS h WHERE h.review_id = r.review_id
        )
    """)


@contextmanager
def _database_connection(database_path: str | Path | None = None) -> Iterator[object]:
    """Open a transaction against SQLite or the configured PostgreSQL pool."""
    target = database_path if database_path is not None else default_database_path()
    try:
        if _is_postgres_target(target):
            pool = _postgres_pool(str(target))
            with pool.connection() as connection:
                with connection.transaction():
                    _ensure_postgres_schema(connection)
                    yield connection
        else:
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path, timeout=10)
            connection.row_factory = sqlite3.Row
            try:
                with connection:
                    connection.execute("PRAGMA foreign_keys = ON")
                    _ensure_sqlite_schema(connection)
                    yield connection
            finally:
                connection.close()
    except (ReviewValidationError, ReviewMigrationError, ReviewStoreError):
        raise
    except Exception:
        raise ReviewStoreError(
            "Review storage operation failed. Check the configured database and retry."
        ) from None


def initialize_review_store(database_path: str | Path | None = None) -> None:
    """Initialize or migrate the current SQLite or PostgreSQL schema in place."""
    with _database_connection(database_path):
        pass


def validate_reviewer_identity(reviewer_identity: str | None) -> str:
    """Require a self-entered name/initials; this does not authenticate anyone."""
    identity = (reviewer_identity or "").strip()
    if not identity:
        raise ReviewValidationError("Enter your name or initials as the reviewer.")
    if len(identity) > MAX_REVIEWER_IDENTITY_LENGTH:
        raise ReviewValidationError(
            f"Reviewer name or initials must be {MAX_REVIEWER_IDENTITY_LENGTH} characters or fewer."
        )
    return identity


def validate_review_record(review_status: str, evidence_examined: str | None,
                           review_conclusion: str | None) -> tuple[str, str, str]:
    if review_status not in REVIEW_STATUSES:
        raise ReviewValidationError(f"Choose one of: {', '.join(REVIEW_STATUSES)}.")
    evidence = (evidence_examined or "").strip()
    conclusion = (review_conclusion or "").strip()
    if review_status in FINAL_STATUSES and not evidence:
        raise ReviewValidationError(
            "Record the evidence examined before marking a review Reviewed or Escalated. "
            "If no evidence was available, document that fact."
        )
    if review_status in FINAL_STATUSES and not conclusion:
        raise ReviewValidationError(
            "Record the auditor's conclusion before marking a review Reviewed or Escalated."
        )
    return review_status, evidence, conclusion


def upsert_review_record(transaction_id: str, review_status: str,
                         evidence_examined: str | None = "",
                         review_conclusion: str | None = "",
                         follow_up_action: str | None = "",
                         database_path: str | Path | None = None,
                         reviewer_identity: str | None = "") -> dict[str, str]:
    """Create/update a review and atomically append its complete saved version."""
    stable_id = str(transaction_id or "").strip()
    if not stable_id:
        raise ReviewValidationError("A transaction ID is required to save a review.")
    identity = validate_reviewer_identity(reviewer_identity)
    status, evidence, conclusion = validate_review_record(
        review_status, evidence_examined, review_conclusion
    )
    follow_up = (follow_up_action or "").strip()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    with _database_connection(database_path) as connection:
        existing = _execute(connection, "SELECT * FROM review_records WHERE transaction_id = ?",
                             (stable_id,)).fetchone()
        if existing is None:
            review_id = str(uuid.uuid4())
            previous_status = None
            _execute(connection, """
                INSERT INTO review_records (
                    transaction_id, review_status, evidence_examined, review_conclusion,
                    follow_up_action, created_at, updated_at, review_id, reviewer_identity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (stable_id, status, evidence, conclusion, follow_up, now, now, review_id, identity))
        else:
            review_id = existing["review_id"]
            previous_status = existing["review_status"]
            _execute(connection, """
                UPDATE review_records SET review_status = ?, evidence_examined = ?,
                    review_conclusion = ?, follow_up_action = ?, updated_at = ?, reviewer_identity = ?
                WHERE transaction_id = ?
            """, (status, evidence, conclusion, follow_up, now, identity, stable_id))
        _execute(connection, """
            INSERT INTO review_history (
                review_id, transaction_id, reviewer_identity, previous_review_status,
                review_status, evidence_examined, review_conclusion, follow_up_action, changed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (review_id, stable_id, identity, previous_status, status,
              evidence, conclusion, follow_up, now))
    saved = get_review_record(stable_id, database_path)
    assert saved is not None
    return saved


def get_review_record(transaction_id: str, database_path: str | Path | None = None) -> dict | None:
    with _database_connection(database_path) as connection:
        row = _execute(connection, "SELECT * FROM review_records WHERE transaction_id = ?",
                       (str(transaction_id).strip(),)).fetchone()
    return dict(row) if row is not None else None


def list_review_records(database_path: str | Path | None = None) -> list[dict]:
    with _database_connection(database_path) as connection:
        rows = _execute(connection,
                        "SELECT * FROM review_records ORDER BY updated_at DESC, transaction_id").fetchall()
    return [dict(row) for row in rows]


def list_review_history(transaction_id: str | None = None,
                        database_path: str | Path | None = None) -> list[dict]:
    with _database_connection(database_path) as connection:
        if transaction_id is None:
            rows = _execute(connection, "SELECT * FROM review_history ORDER BY history_id").fetchall()
        else:
            rows = _execute(connection,
                            "SELECT * FROM review_history WHERE transaction_id = ? ORDER BY history_id",
                            (str(transaction_id).strip(),)).fetchall()
    return [dict(row) for row in rows]


def _csv_bytes(fields: tuple[str, ...], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def review_records_csv_bytes(database_path: str | Path | None = None) -> bytes:
    return _csv_bytes(REVIEW_FIELDS, list_review_records(database_path))


def review_history_csv_bytes(database_path: str | Path | None = None) -> bytes:
    return _csv_bytes(HISTORY_FIELDS, list_review_history(database_path=database_path))


def migrate_sqlite_to_postgres(sqlite_path: str | Path, database_url: str) -> dict[str, int]:
    """Copy records/history idempotently; never overwrite conflicting destination data."""
    if not _is_postgres_target(database_url):
        raise ReviewMigrationError("Migration destination must be a PostgreSQL URL.")
    source = Path(sqlite_path)
    if not source.is_file():
        raise ReviewMigrationError(
            "No SQLite review database was found at the supplied path; there are no local records to migrate."
        )
    validate_postgres_url(database_url)
    initialize_review_store(source)
    with closing(sqlite3.connect(source)) as sqlite_connection:
        sqlite_connection.row_factory = sqlite3.Row
        records = [dict(row) for row in sqlite_connection.execute("SELECT * FROM review_records")]
        history = [dict(row) for row in sqlite_connection.execute(
            "SELECT * FROM review_history ORDER BY history_id"
        )]

    record_fields = tuple(REVIEW_FIELDS)
    history_fields = tuple(HISTORY_FIELDS)
    pool = _postgres_pool(database_url)
    inserted_records = inserted_history = 0
    try:
        with pool.connection() as connection, connection.transaction():
            _ensure_postgres_schema(connection)
            for source_row in records:
                by_transaction = _execute(connection,
                    "SELECT * FROM review_records WHERE transaction_id = ?",
                    (source_row["transaction_id"],)).fetchone()
                by_review_id = _execute(connection,
                    "SELECT * FROM review_records WHERE review_id = ?",
                    (source_row["review_id"],)).fetchone()
                if by_transaction or by_review_id:
                    existing = by_transaction or by_review_id
                    if (existing["transaction_id"] != source_row["transaction_id"]
                            or existing["review_id"] != source_row["review_id"]):
                        raise ReviewMigrationError(
                            "Migration stopped because a transaction or review ID conflicts with an existing PostgreSQL record."
                        )
                    if any(existing[field] != source_row[field] for field in record_fields):
                        raise ReviewMigrationError(
                            "Migration stopped because an existing PostgreSQL review differs from the SQLite source. No records were overwritten."
                        )
                    continue
                columns = ", ".join(record_fields)
                marks = ", ".join("?" for _ in record_fields)
                _execute(connection, f"INSERT INTO review_records ({columns}) VALUES ({marks})",
                         tuple(source_row[field] for field in record_fields))
                inserted_records += 1

            for source_row in history:
                existing = _execute(connection, "SELECT * FROM review_history WHERE history_id = ?",
                                     (source_row["history_id"],)).fetchone()
                if existing:
                    if any(existing[field] != source_row[field] for field in history_fields):
                        raise ReviewMigrationError(
                            "Migration stopped because a history ID conflicts with an existing PostgreSQL version. No history was overwritten."
                        )
                    continue
                columns = ", ".join(history_fields)
                marks = ", ".join("?" for _ in history_fields)
                _execute(connection, f"INSERT INTO review_history ({columns}) VALUES ({marks})",
                         tuple(source_row[field] for field in history_fields))
                inserted_history += 1

            # Read every source row back before committing. This confirms that IDs,
            # timestamps, notes, statuses, and saved versions survived the copy.
            for source_row in records:
                migrated = _execute(
                    connection,
                    "SELECT * FROM review_records WHERE transaction_id = ?",
                    (source_row["transaction_id"],),
                ).fetchone()
                if migrated is None or any(
                    migrated[field] != source_row[field] for field in record_fields
                ):
                    raise ReviewMigrationError(
                        "Migration verification failed for a review record. The PostgreSQL transaction was rolled back."
                    )
            for source_row in history:
                migrated = _execute(
                    connection,
                    "SELECT * FROM review_history WHERE history_id = ?",
                    (source_row["history_id"],),
                ).fetchone()
                if migrated is None or any(
                    migrated[field] != source_row[field] for field in history_fields
                ):
                    raise ReviewMigrationError(
                        "Migration verification failed for a history row. The PostgreSQL transaction was rolled back."
                    )
            _execute(connection, """
                SELECT setval(
                    pg_get_serial_sequence('review_history', 'history_id'),
                    COALESCE(MAX(history_id), 1), COUNT(*) > 0
                ) FROM review_history
            """)
    except (ReviewMigrationError, ReviewStoreError):
        raise
    except Exception:
        raise ReviewStoreError(
            "SQLite migration failed. The PostgreSQL transaction was rolled back; check the provider connection and schema."
        ) from None
    return {"records_inserted": inserted_records, "history_rows_inserted": inserted_history,
            "records_in_source": len(records), "history_rows_in_source": len(history),
            "records_verified": len(records), "history_rows_verified": len(history)}
