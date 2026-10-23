"""Explainable audit-risk screening rules for the synthetic demo."""
from __future__ import annotations

import pandas as pd

RULE_LABELS = {
    "duplicate_payment": "Possible duplicate payment",
    "unusual_amount": "Unusually high amount",
    "weekend_transaction": "Weekend transaction",
    "after_hours_transaction": "After-hours transaction",
    "vendor_concentration": "Vendor concentration",
}


def analyze_transactions(data: pd.DataFrame, amount_percentile: float = 0.99,
                         concentration_share: float = 0.20) -> pd.DataFrame:
    """Return a copy with transparent flags and a human-readable explanation.

    Duplicate candidates match on vendor, amount, and calendar date. The amount
    threshold is calculated from this dataset. Vendor concentration is measured
    as each vendor's share of total spend.
    """
    df = data.copy()
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    key = ["vendor_id", "amount", df["transaction_date"].dt.date]
    df["duplicate_payment"] = df.groupby(key, dropna=False)["transaction_id"].transform("size").gt(1)
    threshold = df["amount"].quantile(amount_percentile)
    df["unusual_amount"] = df["amount"].gt(threshold)
    df["weekend_transaction"] = df["transaction_date"].dt.dayofweek.ge(5)
    df["after_hours_transaction"] = (df["transaction_date"].dt.hour.lt(8) |
                                      df["transaction_date"].dt.hour.ge(18))
    spend = df.groupby("vendor_id")["amount"].transform("sum")
    total = df["amount"].sum()
    df["vendor_spend_share"] = spend / total if total else 0
    df["vendor_concentration"] = df["vendor_spend_share"].ge(concentration_share)
    rule_cols = list(RULE_LABELS)
    df["risk_score"] = df[rule_cols].sum(axis=1)
    df["risk_indicators"] = df.apply(
        lambda row: "; ".join(RULE_LABELS[c] for c in rule_cols if bool(row[c])) or "No rule-based flags",
        axis=1,
    )
    df["amount_threshold"] = threshold
    return df
