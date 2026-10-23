"""SQLite storage for auditor review notes, separate from screening logic."""
from __future__ import annotations

import csv
import io
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

REVIEW_STATUSES = ("Not reviewed", "Under review", "Reviewed", "Escalated")
REVIEW_FIELDS = (
    "transaction_id",
    "review_status",
    "evidence_examined",
    "review_conclusion",
    "follow_up_action",
    "created_at",
    "updated_at",
)
FINAL_STATUSES = {"Reviewed", "Escalated"}


class ReviewValidationError(ValueError):
    """Raised when a review record is incomplete or has an invalid status."""


def default_database_path() -> Path:
    """Return the configured review DB path or the project-local default."""
    configured = os.environ.get("AUDIT_REVIEW_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).parent / "data" / "review_records.sqlite3"


def _connect(database_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(database_path) if database_path is not None else default_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
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
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def initialize_review_store(database_path: str | Path | None = None) -> None:
    """Create the review table if it does not already exist."""
    with closing(_connect(database_path)):
        pass


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
) -> dict[str, str]:
    """Create or update one review record, keyed by the stable transaction ID."""
    stable_id = str(transaction_id or "").strip()
    if not stable_id:
        raise ReviewValidationError("A transaction ID is required to save a review.")
    status, evidence, conclusion = validate_review_record(
        review_status, evidence_examined, review_conclusion
    )
    follow_up = (follow_up_action or "").strip()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    with closing(_connect(database_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO review_records (
                transaction_id, review_status, evidence_examined,
                review_conclusion, follow_up_action, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(transaction_id) DO UPDATE SET
                review_status = excluded.review_status,
                evidence_examined = excluded.evidence_examined,
                review_conclusion = excluded.review_conclusion,
                follow_up_action = excluded.follow_up_action,
                updated_at = excluded.updated_at
            """,
            (stable_id, status, evidence, conclusion, follow_up, now, now),
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
            (str(transaction_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def list_review_records(database_path: str | Path | None = None) -> list[dict[str, str]]:
    """Return all review records, most recently updated first."""
    with closing(_connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM review_records ORDER BY updated_at DESC, transaction_id"
        ).fetchall()
    return [dict(row) for row in rows]


def review_records_csv_bytes(database_path: str | Path | None = None) -> bytes:
    """Serialize all saved review records, including headers when there are none."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(list_review_records(database_path))
    return output.getvalue().encode("utf-8")
