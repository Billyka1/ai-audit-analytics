from collections import Counter
from pathlib import Path

import pandas as pd

import generate_data
from analysis import analyze_transactions


PROJECT_DIR = Path(__file__).resolve().parents[1]


def signature(row):
    timestamp = pd.to_datetime(row.transaction_date)
    return row.vendor_id, row.amount, timestamp.date()


def test_included_dataset_has_only_three_intended_duplicate_groups():
    data = pd.read_csv(PROJECT_DIR / "data" / "transactions.csv")
    analyzed = analyze_transactions(data)
    groups = Counter(signature(row) for row in data.itertuples())
    duplicate_groups = [key for key, count in groups.items() if count > 1]
    duplicate_rows = sum(groups[key] for key in duplicate_groups)
    assert len(data) == 1203
    assert list(data.columns) == [
        "transaction_id", "invoice_id", "vendor_id", "transaction_date", "amount",
        "department", "payment_method", "approver_id", "description",
    ]
    assert len(duplicate_groups) == 3
    assert duplicate_rows == 6
    assert int(analyzed.duplicate_payment.sum()) == 6
    assert analyzed.transaction_id.is_unique


def test_generator_is_reproducible_and_preserves_duplicate_examples(tmp_path, monkeypatch):
    output = tmp_path / "transactions.csv"
    monkeypatch.setattr(generate_data, "OUT", output)
    generate_data.main()
    first = output.read_bytes()
    generate_data.main()
    second = output.read_bytes()
    assert first == second

    data = pd.read_csv(output)
    analyzed = analyze_transactions(data)
    groups = Counter(signature(row) for row in data.itertuples())
    duplicate_groups = [key for key, count in groups.items() if count > 1]
    assert len(data) == 1203
    assert len(duplicate_groups) == 3
    assert int(analyzed.duplicate_payment.sum()) == 6
    assert analyzed["unusual_amount"].any()
    assert analyzed["weekend_transaction"].any()
    assert analyzed["after_hours_transaction"].any()
    assert analyzed["vendor_concentration"].any()
