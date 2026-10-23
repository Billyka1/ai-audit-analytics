from io import BytesIO

import pandas as pd
import pytest

from analysis import analyze_transactions
from review_store import (
    REVIEW_FIELDS,
    ReviewValidationError,
    get_review_record,
    list_review_records,
    review_records_csv_bytes,
    upsert_review_record,
)


def test_save_review_uses_stable_transaction_id_and_accepts_empty_working_notes(tmp_path):
    database = tmp_path / "reviews.sqlite3"
    saved = upsert_review_record(
        " TX00042 ",
        "Under review",
        evidence_examined="",
        review_conclusion=None,
        follow_up_action="",
        database_path=database,
    )

    assert saved["transaction_id"] == "TX00042"
    assert saved["review_status"] == "Under review"
    assert saved["evidence_examined"] == ""
    assert saved["review_conclusion"] == ""
    assert get_review_record("TX00042", database) == saved
    assert get_review_record("TX00043", database) is None


def test_update_review_replaces_fields_without_creating_a_second_record(tmp_path):
    database = tmp_path / "reviews.sqlite3"
    original = upsert_review_record(
        "TX00042", "Under review", "Invoice copy", "Pending approval check", "",
        database_path=database,
    )
    updated = upsert_review_record(
        "TX00042", "Reviewed", "Invoice and approval log", "Payment was authorized.",
        "No further action required.", database_path=database,
    )

    assert len(list_review_records(database)) == 1
    assert updated["transaction_id"] == original["transaction_id"]
    assert updated["created_at"] == original["created_at"]
    assert updated["updated_at"] >= original["updated_at"]
    assert updated["review_status"] == "Reviewed"
    assert updated["evidence_examined"] == "Invoice and approval log"
    assert updated["review_conclusion"] == "Payment was authorized."
    assert updated["follow_up_action"] == "No further action required."


@pytest.mark.parametrize("status", ["Unknown", "Closed", "Confirmed fraud"])
def test_invalid_review_status_is_rejected(tmp_path, status):
    with pytest.raises(ReviewValidationError, match="Choose one of"):
        upsert_review_record("TX00001", status, database_path=tmp_path / "reviews.sqlite3")


def test_missing_transaction_id_is_rejected(tmp_path):
    with pytest.raises(ReviewValidationError, match="transaction ID is required"):
        upsert_review_record("  ", "Not reviewed", database_path=tmp_path / "reviews.sqlite3")


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
        upsert_review_record(
            "TX00001", status, evidence, conclusion,
            database_path=tmp_path / "reviews.sqlite3",
        )


def test_review_export_has_headers_when_empty_and_exports_saved_records(tmp_path):
    database = tmp_path / "reviews.sqlite3"
    empty_export = pd.read_csv(BytesIO(review_records_csv_bytes(database)))
    assert list(empty_export.columns) == list(REVIEW_FIELDS)
    assert empty_export.empty

    upsert_review_record(
        "TX00042", "Under review", "Invoice copy", "Awaiting approval evidence", "",
        database_path=database,
    )
    exported = pd.read_csv(BytesIO(review_records_csv_bytes(database)))
    assert list(exported.columns) == list(REVIEW_FIELDS)
    assert exported.transaction_id.tolist() == ["TX00042"]
    assert exported.review_status.tolist() == ["Under review"]


def test_saving_a_review_does_not_change_screening_rules_or_risk_score(tmp_path):
    transactions = pd.DataFrame([
        {
            "transaction_id": "TX00001",
            "vendor_id": "V001",
            "transaction_date": "2025-01-04 19:15:00",
            "amount": 150.0,
        },
        {
            "transaction_id": "TX00002",
            "vendor_id": "V002",
            "transaction_date": "2025-01-06 11:00:00",
            "amount": 25.0,
        },
    ])
    before = analyze_transactions(transactions)
    upsert_review_record(
        "TX00001", "Under review", "", "", "Check the approval trail.",
        database_path=tmp_path / "reviews.sqlite3",
    )
    after = analyze_transactions(transactions)

    pd.testing.assert_series_equal(before.risk_score, after.risk_score)
    pd.testing.assert_series_equal(before.risk_indicators, after.risk_indicators)
