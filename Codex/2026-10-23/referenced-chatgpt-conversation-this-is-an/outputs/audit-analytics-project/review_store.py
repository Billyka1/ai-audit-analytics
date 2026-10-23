"""SQLite storage for auditor review notes and append-only review history."""
from __future__ import annotations

import csv
import io
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

REVIEW_STATUSES = ("Not reviewed", "Under review", "Reviewed", "Escalated")
REVIEW_FIELDS = (
    "review_id",
    "transaction_id",
    "reviewer_identity",
    "review_status",
    "evidence_examined",
    "review_conclusion",
    "follow_up_action",
    "created_at",
    "updated_at",
)
HISTORY_FIELDS = (
    "history_id",
    "review_id",
    "transaction_id",
    "reviewer_identity",
    "previous_review_status",
    "review_status",
    "evidence_examined",
    "review_conclusion",
    "follow_up_action",
    "changed_at",
)
FINAL_STATUSES = {"Reviewed", "Escalated"}
MAX_REVIEWER_IDENTITY_LENGTH = 100


class ReviewValidationError(ValueError):
    """Raised when a review record is incomplete or has invalid values."""


def default_database_path() -> Path:
    """Return the configured review DB path or the project-local default."""
    configured = os.environ.get("AUDIT_REVIEW_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).parent / "data" / "review_records.sqlite3"


def _utc_now() -> str:
    """Return an ISO 8601 UTC timestamp with an explicit UTC offset."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create current tables and add new columns to an existing review DB."""
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
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(review_records)")
    }
    if "review_id" not in columns:
        connection.execute("ALTER TABLE review_records ADD COLUMN review_id TEXT")
    if "reviewer_identity" not in columns:
        connection.execute(
            "ALTER TABLE review_records ADD COLUMN reviewer_identity TEXT NOT NULL DEFAULT ''"
        )

    # Preserve all existing records and timestamps while assigning each a stable ID.
    rows_without_id = connection.execute(
        "SELECT transaction_id FROM review_records WHERE review_id IS NULL OR review_id = ''"
    ).fetchall()
    for row in rows_without_id:
        connection.execute(
            "UPDATE review_records SET review_id = ? WHERE transaction_id = ?",
            (str(uuid.uuid4()), row["transaction_id"]),
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_review_records_review_id "
        "ON review_records(review_id)"
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
        "CREATE INDEX IF NOT EXISTS idx_review_history_transaction "
        "ON review_history(transaction_id, history_id)"
    )
    # Seed one last-known snapshot for legacy reviews so their next update does
    # not erase the only version that existed before history was introduced.
    connection.execute(
        """
        INSERT INTO review_history (
            review_id, transaction_id, reviewer_identity, previous_review_status,
            review_status, evidence_examined, review_conclusion,
            follow_up_action, changed_at
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
    connection.commit()


def _connect(database_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(database_path) if database_path is not None else default_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(connection)
    return connection


def initialize_review_store(database_path: str | Path | None = None) -> None:
    """Initialize or migrate the SQLite schema without replacing stored rows."""
    with closing(_connect(database_path)):
        pass


def validate_reviewer_identity(reviewer_identity: str | None) -> str:
    """Require a self-entered name/initials, without asserting authentication."""
    identity = (reviewer_identity or "").strip()
    if not identity:
        raise ReviewValidationError("Enter your name or initials as the reviewer.")
    if len(identity) > MAX_REVIEWER_IDENTITY_LENGTH:
        raise ReviewValidationError(
            f"Reviewer name or initials must be {MAX_REVIEWER_IDENTITY_LENGTH} characters or fewer."
        )
    return identity


def validate_review_record(
    review_status: str,
    evidence_examined: str | None,
    review_conclusion: str | None,
) -> tuple[str, str, str]:
    """Validate status and completed-review documentation; return trimmed notes."""
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


def upsert_review_record(
    transaction_id: str,
    review_status: str,
    evidence_examined: str | None = "",
    review_conclusion: str | None = "",
    follow_up_action: str | None = "",
    database_path: str | Path | None = None,
    reviewer_identity: str | None = "",
) -> dict[str, str]:
    """Create/update a review and append a complete saved-version history row."""
    stable_id = str(transaction_id or "").strip()
    if not stable_id:
        raise ReviewValidationError("A transaction ID is required to save a review.")
    identity = validate_reviewer_identity(reviewer_identity)
    status, evidence, conclusion = validate_review_record(
        review_status, evidence_examined, review_conclusion
    )
    follow_up = (follow_up_action or "").strip()
    now = _utc_now()

    with closing(_connect(database_path)) as connection, connection:
        existing = connection.execute(
            "SELECT * FROM review_records WHERE transaction_id = ?", (stable_id,)
        ).fetchone()
        if existing is None:
            review_id = str(uuid.uuid4())
            created_at = now
            previous_status = None
            connection.execute(
                """
                INSERT INTO review_records (
                    transaction_id, review_status, evidence_examined,
                    review_conclusion, follow_up_action, created_at, updated_at,
                    review_id, reviewer_identity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (stable_id, status, evidence, conclusion, follow_up,
                 created_at, now, review_id, identity),
            )
        else:
            review_id = existing["review_id"]
            created_at = existing["created_at"]
            previous_status = existing["review_status"]
            connection.execute(
                """
                UPDATE review_records SET
                    review_status = ?, evidence_examined = ?, review_conclusion = ?,
                    follow_up_action = ?, updated_at = ?, reviewer_identity = ?
                WHERE transaction_id = ?
                """,
                (status, evidence, conclusion, follow_up, now, identity, stable_id),
            )

        connection.execute(
            """
            INSERT INTO review_history (
                review_id, transaction_id, reviewer_identity, previous_review_status,
                review_status, evidence_examined, review_conclusion,
                follow_up_action, changed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, stable_id, identity, previous_status, status,
             evidence, conclusion, follow_up, now),
        )

    saved = get_review_record(stable_id, database_path)
    assert saved is not None
    return saved


def get_review_record(
    transaction_id: str,
    database_path: str | Path | None = None,
) -> dict[str, str] | None:
    """Fetch the saved review associated with one stable transaction ID."""
    with closing(_connect(database_path)) as connection:
        row = connection.execute(
            "SELECT * FROM review_records WHERE transaction_id = ?",
            (str(transaction_id).strip(),),
        ).fetchone()
    return dict(row) if row is not None else None


def list_review_records(database_path: str | Path | None = None) -> list[dict[str, str]]:
    """Return current review records, most recently updated first."""
    with closing(_connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM review_records ORDER BY updated_at DESC, transaction_id"
        ).fetchall()
    return [dict(row) for row in rows]


def list_review_history(
    transaction_id: str | None = None,
    database_path: str | Path | None = None,
) -> list[dict[str, str | int | None]]:
    """Return saved versions in chronological order, optionally for one transaction."""
    with closing(_connect(database_path)) as connection:
        if transaction_id is None:
            rows = connection.execute(
                "SELECT * FROM review_history ORDER BY history_id"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM review_history WHERE transaction_id = ? ORDER BY history_id",
                (str(transaction_id).strip(),),
            ).fetchall()
    return [dict(row) for row in rows]


def _csv_bytes(fields: tuple[str, ...], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def review_records_csv_bytes(database_path: str | Path | None = None) -> bytes:
    """Serialize current review records, including headers when empty."""
    return _csv_bytes(REVIEW_FIELDS, list_review_records(database_path))


def review_history_csv_bytes(database_path: str | Path | None = None) -> bytes:
    """Serialize all saved versions, including headers when history is empty."""
    return _csv_bytes(HISTORY_FIELDS, list_review_history(database_path=database_path))
