"""Interactive Streamlit dashboard for synthetic audit analytics."""
from pathlib import Path
import pandas as pd
import streamlit as st

from analysis import (
    analyze_transactions,
    dashboard_metrics,
    filter_transactions,
    rule_count_chart_data,
    screened_csv_bytes,
    vendor_spend_chart_data,
)

DATA_PATH = Path(__file__).parent / "data" / "transactions.csv"
st.set_page_config(page_title="Audit Analytics | Risk Explorer", page_icon="🔎", layout="wide")
st.title("🔎 AI-Powered Audit Analytics & Fraud Risk Detection")
st.caption("Synthetic portfolio demonstration · Rule-Based Audit Risk Screening and Transaction Analytics")

@st.cache_data
def load_data():
    return pd.read_csv(DATA_PATH)

raw = load_data()
st.sidebar.header("Explore the data")
min_date, max_date = pd.to_datetime(raw.transaction_date).dt.date.agg(["min", "max"])
date_range = st.sidebar.date_input("Transaction date range", (min_date, max_date), min_value=min_date, max_value=max_date)
vendors = sorted(raw.vendor_id.unique())
selected_vendors = st.sidebar.multiselect("Vendors", vendors, default=vendors)
percentile = st.sidebar.slider("Unusual amount threshold percentile", 90, 100, 99, 1) / 100
concentration = st.sidebar.slider("Vendor concentration threshold (% of spend)", 5, 50, 20, 1) / 100

df = analyze_transactions(raw, percentile, concentration)
df = filter_transactions(df, date_range=date_range, vendors=selected_vendors)
flagged = df[df.risk_score > 0]
metrics = dashboard_metrics(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Transactions", f"{metrics['transactions']:,}")
c2.metric("Spend screened", f"${metrics['spend']:,.0f}")
c3.metric(
    "Transactions with flags",
    f"{metrics['flagged_transactions']:,}",
    help=f"{metrics['flag_rate']:.1%} of screened rows have one or more rule-based indicators.",
)
c4.metric("Rule hits", f"{metrics['rule_hits']:,}")

left, right = st.columns(2)
with left:
    st.subheader("Flags by rule")
    counts = rule_count_chart_data(df)
    if df.empty:
        st.caption("No matching transactions. Rule counts are zero for this selection.")
    else:
        st.bar_chart(counts, x="transactions", y="rule", horizontal=True, sort="-transactions")
with right:
    st.subheader("Spend by vendor")
    spend = vendor_spend_chart_data(df)
    if spend.empty:
        st.caption("No vendor spend for this selection.")
    else:
        st.bar_chart(spend, x="spend", y="vendor_id", horizontal=True, sort="-spend")

st.subheader("Flagged transactions")
show = ["transaction_id", "transaction_date", "vendor_id", "amount", "department", "risk_score", "risk_indicators"]
st.dataframe(flagged[show].sort_values(["risk_score", "amount"], ascending=False), width="stretch", hide_index=True)
st.download_button("Download screened transactions as CSV", screened_csv_bytes(df),
                   "screened_transactions.csv", "text/csv")
st.info("The dataset is synthetic. Each risk score counts triggered rules; it is not a fraud probability. A flag is an indicator for human review, not proof of fraud or misconduct. Vendor concentration is not automatically suspicious.")
with st.expander("How the rules work"):
    st.markdown("""
- **Possible duplicate:** same vendor, amount, and calendar date appears more than once.
- **Unusually high amount:** amount is above the selected dataset percentile.
- **Weekend / after-hours:** timestamp falls on Saturday or Sunday, or before 08:00 / at or after 18:00.
- **Vendor concentration:** vendor's total spend is at least the selected share of total screened spend.

These are intentionally simple, interpretable rules. The project title uses “AI” as a portfolio theme; this first version does not train a machine-learning model.
""")
