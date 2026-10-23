"""Interactive Streamlit dashboard for synthetic audit analytics."""
from pathlib import Path
import pandas as pd
import streamlit as st

from analysis import analyze_transactions, RULE_LABELS

DATA_PATH = Path(__file__).parent / "data" / "transactions.csv"
st.set_page_config(page_title="Audit Analytics | Risk Explorer", page_icon="🔎", layout="wide")
st.title("🔎 AI-Powered Audit Analytics & Fraud Risk Detection")
st.caption("Synthetic portfolio demo · Explainable screening rules · Not an automated fraud verdict")

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
if isinstance(date_range, tuple) and len(date_range) == 2:
    dates = pd.to_datetime(df.transaction_date).dt.date
    df = df[dates.between(date_range[0], date_range[1])]
df = df[df.vendor_id.isin(selected_vendors)]
flagged = df[df.risk_score > 0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Transactions", f"{len(df):,}")
c2.metric("Spend screened", f"${df.amount.sum():,.0f}")
c3.metric("Transactions with flags", f"{len(flagged):,}", f"{len(flagged)/len(df):.1%}" if len(df) else "0%")
c4.metric("Rule hits", f"{int(df.risk_score.sum()):,}")

left, right = st.columns(2)
with left:
    st.subheader("Flags by rule")
    counts = pd.Series({label: int(df[column].sum()) for column, label in RULE_LABELS.items()}).sort_values()
    st.bar_chart(counts)
with right:
    st.subheader("Spend by vendor")
    spend = df.groupby("vendor_id").amount.sum().sort_values(ascending=False).head(12)
    st.bar_chart(spend)

st.subheader("Flagged transactions")
show = ["transaction_id", "transaction_date", "vendor_id", "amount", "department", "risk_score", "risk_indicators"]
st.dataframe(flagged[show].sort_values(["risk_score", "amount"], ascending=False), use_container_width=True, hide_index=True)
st.download_button("Download screened transactions as CSV", df.to_csv(index=False).encode("utf-8"),
                   "screened_transactions.csv", "text/csv")
st.info("A flag is a prompt for follow-up, not proof of fraud or misconduct. Validate source records, understand business context, and document review conclusions.")
with st.expander("How the rules work"):
    st.markdown("""
- **Possible duplicate:** same vendor, amount, and calendar date appears more than once.
- **Unusually high amount:** amount is above the selected dataset percentile.
- **Weekend / after-hours:** timestamp falls on Saturday or Sunday, or before 08:00 / at or after 18:00.
- **Vendor concentration:** vendor's total spend is at least the selected share of total screened spend.

These are intentionally simple, interpretable rules. The project title uses “AI” as a portfolio theme; this first version does not train a machine-learning model.
""")
