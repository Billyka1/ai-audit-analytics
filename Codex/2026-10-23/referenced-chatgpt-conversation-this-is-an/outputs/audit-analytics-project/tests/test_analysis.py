from datetime import date
from io import BytesIO

import pandas as pd
import pytest

from analysis import (
    RULE_LABELS,
    analyze_transactions,
    dashboard_metrics,
    filter_transactions,
    rule_count_chart_data,
    screened_csv_bytes,
    vendor_spend_chart_data,
)


def transactions(rows):
    defaults = {
        "transaction_date": "2025-01-06 12:00:00",
        "vendor_id": "V001",
        "amount": 10.0,
    }
    records = []
    for index, row in enumerate(rows, start=1):
        records.append({**defaults, **row, "transaction_id": f"T{index:03d}"})
    return pd.DataFrame(records)


def test_duplicate_signature_flags_both_rows_and_only_exact_matches():
    data = transactions([
        {"vendor_id": "A", "amount": 100},
        {"vendor_id": "A", "amount": 100},
        {"vendor_id": "A", "amount": 101},
        {"vendor_id": "B", "amount": 100},
        {"vendor_id": "A", "amount": 100, "transaction_date": "2025-01-07 12:00:00"},
    ])
    result = analyze_transactions(data, amount_percentile=1, concentration_share=1)
    assert result.duplicate_payment.tolist() == [True, True, False, False, False]
    assert int(result.duplicate_payment.sum()) == 2  # Both records in the group are flagged.


def test_high_amount_quantile_is_strictly_greater_than_boundary():
    data = transactions([{"vendor_id": f"V{i}", "amount": n} for i, n in enumerate([10, 20, 30, 40, 50])])
    result = analyze_transactions(data, amount_percentile=0.5, concentration_share=1)
    assert result.amount_threshold.iloc[0] == 30
    assert result.unusual_amount.tolist() == [False, False, False, True, True]


def test_weekend_flags_saturday_and_sunday_but_not_monday():
    data = transactions([
        {"transaction_date": "2025-01-04 12:00:00"},  # Saturday
        {"transaction_date": "2025-01-05 12:00:00"},  # Sunday
        {"transaction_date": "2025-01-06 12:00:00"},  # Monday
    ])
    result = analyze_transactions(data, amount_percentile=1, concentration_share=1)
    assert result.weekend_transaction.tolist() == [True, True, False]


def test_after_hours_boundaries_are_before_0800_and_at_or_after_1800():
    data = transactions([
        {"transaction_date": "2025-01-06 07:59:00"},
        {"transaction_date": "2025-01-06 08:00:00"},
        {"transaction_date": "2025-01-06 17:59:00"},
        {"transaction_date": "2025-01-06 18:00:00"},
        {"transaction_date": "2025-01-06 18:01:00"},
    ])
    result = analyze_transactions(data, amount_percentile=1, concentration_share=1)
    assert result.after_hours_transaction.tolist() == [True, False, False, True, True]


def test_vendor_concentration_includes_exact_threshold():
    data = transactions([
        {"vendor_id": "A", "amount": 10},
        {"vendor_id": "B", "amount": 40},
        {"vendor_id": "C", "amount": 50},
    ])
    result = analyze_transactions(data, amount_percentile=1, concentration_share=0.40)
    assert result.vendor_spend_share.tolist() == pytest.approx([0.10, 0.40, 0.50])
    assert result.vendor_concentration.tolist() == [False, True, True]


def test_zero_total_spend_has_no_vendor_concentration_flags():
    result = analyze_transactions(
        transactions([{"vendor_id": "A", "amount": 0}, {"vendor_id": "B", "amount": 0}]),
        amount_percentile=1,
        concentration_share=0,
    )
    assert result.vendor_spend_share.tolist() == [0.0, 0.0]
    assert result.vendor_concentration.tolist() == [False, False]


def test_risk_score_counts_rules_and_unique_flags_are_not_double_counted():
    data = transactions([
        {"transaction_date": "2025-01-04 19:00:00", "vendor_id": "A", "amount": 100},
        {"transaction_date": "2025-01-04 19:00:00", "vendor_id": "A", "amount": 100},
    ])
    result = analyze_transactions(data, amount_percentile=1, concentration_share=0.4)
    assert result.risk_score.tolist() == [4, 4]  # Duplicate, weekend, after-hours, concentration.
    assert "Possible duplicate payment" in result.risk_indicators.iloc[0]
    assert "Weekend transaction" in result.risk_indicators.iloc[0]
    metrics = dashboard_metrics(result)
    assert metrics["flagged_transactions"] == 2
    assert metrics["rule_hits"] == 8
    assert metrics["transactions"] == 2


def test_dashboard_filters_combine_and_metrics_follow_filtered_rows():
    raw = transactions([
        {"vendor_id": "A", "amount": 10, "transaction_date": "2025-01-06 12:00:00"},
        {"vendor_id": "B", "amount": 20, "transaction_date": "2025-01-07 12:00:00"},
        {"vendor_id": "A", "amount": 30, "transaction_date": "2025-01-11 12:00:00"},
    ])
    analyzed = analyze_transactions(raw)
    by_date = filter_transactions(analyzed, (date(2025, 1, 6), date(2025, 1, 7)))
    by_vendor = filter_transactions(analyzed, vendors=["A"])
    combined = filter_transactions(analyzed, (date(2025, 1, 6), date(2025, 1, 7)), ["A"])
    assert by_date.transaction_id.tolist() == ["T001", "T002"]
    assert by_vendor.transaction_id.tolist() == ["T001", "T003"]
    assert combined.transaction_id.tolist() == ["T001"]
    assert dashboard_metrics(combined)["spend"] == 10
    assert dashboard_metrics(combined)["transactions"] == 1
    csv_round_trip = pd.read_csv(BytesIO(screened_csv_bytes(combined)))
    assert csv_round_trip.transaction_id.tolist() == ["T001"]


def test_slider_thresholds_change_rule_flags_without_refitting_on_filtered_subset():
    raw = transactions([
        {"vendor_id": "A", "amount": 10},
        {"vendor_id": "B", "amount": 20},
        {"vendor_id": "C", "amount": 30},
        {"vendor_id": "D", "amount": 40},
    ])
    low_cutoff = analyze_transactions(raw, amount_percentile=0.25, concentration_share=0.5)
    high_cutoff = analyze_transactions(raw, amount_percentile=0.75, concentration_share=0.5)
    assert int(low_cutoff.unusual_amount.sum()) == 3
    assert int(high_cutoff.unusual_amount.sum()) == 1
    low_concentration = analyze_transactions(raw, amount_percentile=1, concentration_share=0.25)
    high_concentration = analyze_transactions(raw, amount_percentile=1, concentration_share=0.50)
    assert int(low_concentration.vendor_concentration.sum()) == 2
    assert int(high_concentration.vendor_concentration.sum()) == 0


def test_charts_use_explicit_values_and_top_vendor_order():
    result = analyze_transactions(transactions([
        {"vendor_id": "A", "amount": 10},
        {"vendor_id": "B", "amount": 30},
        {"vendor_id": "C", "amount": 20},
    ]))
    counts = rule_count_chart_data(result)
    vendors = vendor_spend_chart_data(result, limit=2)
    assert list(counts.columns) == ["rule", "transactions"]
    assert set(counts.rule) == set(RULE_LABELS.values())
    assert list(vendors.columns) == ["vendor_id", "spend"]
    assert vendors.vendor_id.tolist() == ["B", "C"]
    assert vendors.spend.tolist() == [30, 20]


def test_empty_filtered_data_produces_safe_metrics_charts_and_csv():
    analyzed = analyze_transactions(transactions([{"vendor_id": "A", "amount": 10}]))
    empty = filter_transactions(analyzed, vendors=[])
    metrics = dashboard_metrics(empty)
    counts = rule_count_chart_data(empty)
    vendors = vendor_spend_chart_data(empty)
    round_trip = pd.read_csv(BytesIO(screened_csv_bytes(empty)))
    assert metrics == {
        "transactions": 0,
        "spend": 0.0,
        "flagged_transactions": 0,
        "flag_rate": 0.0,
        "rule_hits": 0,
    }
    assert len(counts) == 5 and counts.transactions.eq(0).all()
    assert vendors.empty
    assert round_trip.empty


@pytest.mark.parametrize("percentile,share", [(-0.1, 0.2), (1.1, 0.2), (0.9, -0.1), (0.9, 1.1)])
def test_thresholds_outside_zero_to_one_are_rejected(percentile, share):
    with pytest.raises(ValueError):
        analyze_transactions(transactions([{"amount": 1}]), percentile, share)
