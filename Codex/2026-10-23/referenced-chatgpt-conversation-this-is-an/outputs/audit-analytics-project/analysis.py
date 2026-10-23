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
    if not 0 <= amount_percentile <= 1:
        raise ValueError("amount_percentile must be between 0 and 1")
    if not 0 <= concentration_share <= 1:
        raise ValueError("concentration_share must be between 0 and 1")

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
    has_positive_total = total > 0
    df["vendor_spend_share"] = spend / total if has_positive_total else 0.0
    # A zero or negative total cannot establish a meaningful spend share.
    df["vendor_concentration"] = (df["vendor_spend_share"].ge(concentration_share)
                                  if has_positive_total else False)
    rule_cols = list(RULE_LABELS)
    df["risk_score"] = df[rule_cols].sum(axis=1)
    df["risk_indicators"] = df.apply(
        lambda row: "; ".join(RULE_LABELS[c] for c in rule_cols if bool(row[c])) or "No rule-based flags",
        axis=1,
    )
    df["amount_threshold"] = threshold
    return df


def filter_transactions(data: pd.DataFrame, date_range=None, vendors=None) -> pd.DataFrame:
    """Apply dashboard filters to already-analyzed rows.

    Screening thresholds and flags should be calculated before this function,
    so navigating a subset does not change the screening population.
    """
    df = data.copy()
    if date_range is not None and len(date_range) == 2:
        start, end = date_range
        transaction_days = df["transaction_date"].dt.date
        df = df.loc[transaction_days.between(start, end)]
    if vendors is not None:
        df = df.loc[df["vendor_id"].isin(vendors)]
    return df.copy()


def rule_count_chart_data(data: pd.DataFrame) -> pd.DataFrame:
    """Return explicit category/value columns for the rule-hit chart."""
    return (pd.DataFrame({
        "rule": [label for label in RULE_LABELS.values()],
        "transactions": [int(data[column].sum()) for column in RULE_LABELS],
    }).sort_values("transactions", ascending=True, kind="stable").reset_index(drop=True))


def vendor_spend_chart_data(data: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    """Return top vendor spend with explicit vendor and amount columns."""
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return (data.groupby("vendor_id", as_index=False)["amount"].sum()
            .rename(columns={"amount": "spend"})
            .sort_values("spend", ascending=False, kind="stable")
            .head(limit).reset_index(drop=True))


def dashboard_metrics(data: pd.DataFrame) -> dict[str, float | int]:
    """Summarize the currently displayed transaction population."""
    flagged = data["risk_score"].gt(0)
    count = len(data)
    return {
        "transactions": count,
        "spend": float(data["amount"].sum()),
        "flagged_transactions": int(flagged.sum()),
        "flag_rate": float(flagged.mean()) if count else 0.0,
        "rule_hits": int(data["risk_score"].sum()),
    }


def screened_csv_bytes(data: pd.DataFrame) -> bytes:
    """Serialize the displayed screened population for the dashboard download."""
    return data.to_csv(index=False).encode("utf-8")
