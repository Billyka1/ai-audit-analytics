from datetime import datetime, timezone
from io import BytesIO
import sqlite3

import pandas as pd
import pytest

from analysis import analyze_transactions
from review_store import (
    HISTORY_FIELDS,
    REVIEW_FIELDS,
    ReviewValidationError,
    get_review_record,
    initialize_review_store,
    list_review_history,
    list_review_records,
    review_history_csv_bytes,
    review_records_csv_bytes,
    upsert_review_record,
    validate_reviewer_identity,
)


def save(database, transaction_id="TX00042", reviewer_identity="AB", **values):
    return upsert_review_record(
        transaction_id=transaction_id,
        review_status=values.pop("review_status", "Under review"),
        database_path=database,
        reviewer_identity=reviewer_identity,
        **values,
    )


def test_save_review_uses_stable_transaction_and_review_ids_and_utc_timestamps(tmp_path):
    database = tmp_path / "reviews.sqlite3"
    saved = save(
        database,
        transaction_id=" TX00042 ",
        evidence_examined="",
        review_conclusion=None,
        follow_up_action="",
    )

    assert saved["transaction_id"] == "TX00042"
    assert saved["reviewer_identity"] == "AB"
    assert saved["review_id"]
    assert get_review_record("TX00042", database) == saved
    assert get_review_record("TX00043", database) is None
    for field in ("created_at", "updated_at"):
        stamp = datetime.fromisoformat(saved[field])
        assert stamp.tzinfo == timezone.utc


def test_update_preserves_ids_and_creation_timestamp_and_appends_full_history(tmp_path):
    database = tmp_path / "reviews.sqlite3"
    original = save(
        database,
        reviewer_identity="AB",
        review_status="Under review",
        evidence_examined="Invoice copy",
        review_conclusion="Approval evidence pending",
        follow_up_action="Request approval log",
    )
    updated = save(
        database,
        reviewer_identity="CD",
        review_status="Reviewed",
        evidence_examined="Invoice and approval log",
        review_conclusion="Payment is supported by the documents examined.",
        follow_up_action="No further action required.",
    )

    assert len(list_review_records(database)) == 1
    assert updated["transaction_id"] == original["transaction_id"]
    assert updated["review_id"] == original["review_id"]
    assert updated["created_at"] == original["created_at"]
    assert updated["updated_at"] >= original["updated_at"]
    assert updated["reviewer_identity"] == "CD"
    history = list_review_history(transaction_id="TX00042", database_path=database)
    assert len(history) == 2
    assert history[0]["review_id"] == history[1]["review_id"] == original["review_id"]
    assert history[0]["transaction_id"] == history[1]["transaction_id"] == "TX00042"
    assert history[0]["previous_review_status"] is None
    assert history[0]["review_status"] == "Under review"
    assert history[0]["evidence_examined"] == "Invoice copy"
    assert history[0]["reviewer_identity"] == "AB"
    assert history[1]["previous_review_status"] == "Under review"
    assert history[1]["review_status"] == "Reviewed"
    assert history[1]["evidence_examined"] == "Invoice and approval log"
    assert history[1]["review_conclusion"] == updated["review_conclusion"]
    assert history[1]["follow_up_action"] == updated["follow_up_action"]
    assert history[1]["reviewer_identity"] == "CD"
    assert datetime.fromisoformat(history[1]["changed_at"]).tzinfo == timezone.utc


@pytest.mark.parametrize("identity", [None, "", "   "])
def test_reviewer_identity_must_not_be_empty(identity):
    with pytest.raises(ReviewValidationError, match="Enter your name or initials"):
        validate_reviewer_identity(identity)


def test_reviewer_identity_is_trimmed_and_length_limited():
    assert validate_reviewer_identity("  A.B.  ") == "A.B."
    with pytest.raises(ReviewValidationError, match="100 characters or fewer"):
        validate_reviewer_identity("x" * 101)


def test_identity_validation_prevents_save(tmp_path):
    with pytest.raises(ReviewValidationError, match="Enter your name or initials"):
        save(tmp_path / "reviews.sqlite3", reviewer_identity=" ")


@pytest.mark.parametrize("status", ["Unknown", "Closed", "Confirmed fraud"])
def test_invalid_review_status_is_rejected(tmp_path, status):
    with pytest.raises(ReviewValidationError, match="Choose one of"):
        save(tmp_path / "reviews.sqlite3", review_status=status)


def test_missing_transaction_id_is_rejected(tmp_path):
    with pytest.raises(ReviewValidationError, match="transaction ID is required"):
        save(tmp_path / "reviews.sqlite3", transaction_id="  ")


@pytest.mark.parametrize("status", ["Reviewed", "Escalated"])
@pytest.mark.parametrize(
    "evidence,conclusion,expected_message",
    [
        ("", "A conclusion", "evidence examined"),
        ("Invoice and approval record", "", "auditor's conclusion"),
    ],
)
def test_completed_or_escalated_review_requires_evidence_and_conclusion(
    tmp_path, status, evidence, conclusion, expected_message
):
    with pytest.raises(ReviewValidationError, match=expected_message):
        save(
            tmp_path / "reviews.sqlite3",
            review_status=status,
            evidence_examined=evidence,
            review_conclusion=conclusion,
        )


def test_csv_exports_have_headers_when_empty_and_export_ids_identity_and_versions(tmp_path):
    database = tmp_path / "reviews.sqlite3"
    empty_reviews = pd.read_csv(BytesIO(review_records_csv_bytes(database)))
    empty_history = pd.read_csv(BytesIO(review_history_csv_bytes(database)))
    assert list(empty_reviews.columns) == list(REVIEW_FIELDS)
    assert list(empty_history.columns) == list(HISTORY_FIELDS)
    assert empty_reviews.empty and empty_history.empty

    saved = save(database, reviewer_identity="EF", evidence_examined="Invoice", review_conclusion="Pending")
    save(database, reviewer_identity="GH", review_status="Reviewed",
         evidence_examined="Invoice and approval", review_conclusion="Supported")
    current = pd.read_csv(BytesIO(review_records_csv_bytes(database)))
    history = pd.read_csv(BytesIO(review_history_csv_bytes(database)))
    assert list(current.columns) == list(REVIEW_FIELDS)
    assert list(history.columns) == list(HISTORY_FIELDS)
    assert current.transaction_id.tolist() == ["TX00042"]
    assert current.review_id.tolist() == [saved["review_id"]]
    assert current.reviewer_identity.tolist() == ["GH"]
    assert history.transaction_id.tolist() == ["TX00042", "TX00042"]
    assert history.reviewer_identity.tolist() == ["EF", "GH"]
    assert history.review_status.tolist() == ["Under review", "Reviewed"]


def test_initialize_migrates_legacy_db_in_place_without_losing_review_data(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE review_records (
            transaction_id TEXT PRIMARY KEY,
            review_status TEXT NOT NULL,
            evidence_examined TEXT NOT NULL DEFAULT '',
            review_conclusion TEXT NOT NULL DEFAULT '',
            follow_up_action TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        "INSERT INTO review_records VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("TXLEGACY", "Under review", "Old invoice note", "Pending", "Ask AP", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()

    initialize_review_store(database)
    migrated = get_review_record("TXLEGACY", database)
    assert migrated["transaction_id"] == "TXLEGACY"
    assert migrated["review_id"]
    assert migrated["reviewer_identity"] == ""
    assert migrated["created_at"] == "2026-01-01T00:00:00+00:00"
    assert migrated["updated_at"] == "2026-01-02T00:00:00+00:00"
    legacy_history = list_review_history(database_path=database)
    assert len(legacy_history) == 1
    assert legacy_history[0]["previous_review_status"] is None
    assert legacy_history[0]["review_status"] == "Under review"
    assert legacy_history[0]["evidence_examined"] == "Old invoice note"
    assert legacy_history[0]["reviewer_identity"] == ""
    assert legacy_history[0]["changed_at"] == migrated["updated_at"]

    updated = save(database, transaction_id="TXLEGACY", reviewer_identity="IJ")
    assert updated["review_id"] == migrated["review_id"]
    assert updated["created_at"] == migrated["created_at"]
    history = list_review_history("TXLEGACY", database)
    assert len(history) == 2
    assert history[0]["review_status"] == "Under review"
    assert history[1]["previous_review_status"] == "Under review"


def test_saving_a_review_does_not_change_screening_rules_or_risk_score(tmp_path):
    transactions = pd.DataFrame([
        {"transaction_id": "TX00001", "vendor_id": "V001", "transaction_date": "2025-01-04 19:15:00", "amount": 150.0},
        {"transaction_id": "TX00002", "vendor_id": "V002", "transaction_date": "2025-01-06 11:00:00", "amount": 25.0},
    ])
    before = analyze_transactions(transactions)
    save(
        tmp_path / "reviews.sqlite3",
        transaction_id="TX00001",
        evidence_examined="Invoice checked",
        review_conclusion="Further review required",
        follow_up_action="Check approval trail.",
    )
    after = analyze_transactions(transactions)
    pd.testing.assert_series_equal(before.risk_score, after.risk_score)
    pd.testing.assert_series_equal(before.risk_indicators, after.risk_indicators)
