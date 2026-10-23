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
from review_store import (
    REVIEW_STATUSES,
    default_database_path,
    initialize_review_store,
    list_review_records,
    review_records_csv_bytes,
    upsert_review_record,
)

DATA_PATH = Path(__file__).parent / "data" / "transactions.csv"
st.set_page_config(page_title="Audit Analytics | Risk Explorer", page_icon="🔎", layout="wide")
st.title("🔎 AI-Powered Audit Analytics & Fraud Risk Detection")
st.caption("Synthetic portfolio demonstration · Rule-Based Audit Risk Screening and Transaction Analytics")

@st.cache_data
def load_data():
    return pd.read_csv(DATA_PATH)

raw = load_data()
review_db_path = default_database_path()
initialize_review_store(review_db_path)
st.sidebar.header("Explore the data")
min_date, max_date = pd.to_datetime(raw.transaction_date).dt.date.agg(["min", "max"])
date_range = st.sidebar.date_input("Transaction date range", (min_date, max_date), min_value=min_date, max_value=max_date)
vendors = sorted(raw.vendor_id.unique())
selected_vendors = st.sidebar.multiselect("Vendors", vendors, default=vendors)
percentile = st.sidebar.slider("Unusual amount threshold percentile", 90, 100, 99, 1) / 100
concentration = st.sidebar.slider("Vendor concentration threshold (% of spend)", 5, 50, 20, 1) / 100

screened = analyze_transactions(raw, percentile, concentration)
df = filter_transactions(screened, date_range=date_range, vendors=selected_vendors)
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

st.divider()
st.subheader("Auditor review workflow")
st.caption(
    "Document review work separately from transaction screening. Saving a review never "
    "changes the screening rules, risk score, or original transaction data."
)
st.info(
    "A screening indicator is a potential exception for review, not a confirmed fraud finding. "
    "Use factual notes and retain evidence according to the applicable audit process."
)
st.warning(
    "Portfolio-demo limitation: this public app has no sign-in. Anyone with access can add "
    "or update review records. Use synthetic notes only; do not enter confidential or real audit information."
)

if flagged.empty:
    st.warning(
        "No flagged transactions are available to review under the current date, vendor, "
        "and screening settings. Existing review records remain available below."
    )
else:
    flagged_for_review = flagged.sort_values(
        ["risk_score", "amount"], ascending=False
    ).drop_duplicates("transaction_id").set_index("transaction_id", drop=False)

    def review_option_label(transaction_id: str) -> str:
        row = flagged_for_review.loc[transaction_id]
        return (
            f"{transaction_id} · {row['vendor_id']} · "
            f"${row['amount']:,.2f} · score {int(row['risk_score'])}"
        )

    selected_transaction_id = st.selectbox(
        "Select a flagged transaction",
        options=flagged_for_review.index.tolist(),
        format_func=review_option_label,
        key="review_transaction_id",
    )
    selected_row = flagged_for_review.loc[selected_transaction_id]
    existing = next(
        (record for record in list_review_records(review_db_path)
         if record["transaction_id"] == selected_transaction_id),
        None,
    )

    st.markdown("**Transaction details and screening results**")
    transaction_details = pd.DataFrame([{
        "Transaction ID": selected_row["transaction_id"],
        "Date and time": selected_row["transaction_date"],
        "Vendor": selected_row["vendor_id"],
        "Amount": selected_row["amount"],
        "Department": selected_row.get("department", ""),
        "Payment method": selected_row.get("payment_method", ""),
        "Approver": selected_row.get("approver_id", ""),
        "Description": selected_row.get("description", ""),
        "Screening risk score": int(selected_row["risk_score"]),
        "Risk indicators": selected_row["risk_indicators"],
    }])
    st.dataframe(transaction_details, width="stretch", hide_index=True)

    if existing:
        st.caption(
            f"Existing review record · status: {existing['review_status']} · "
            f"last updated (UTC): {existing['updated_at']}"
        )
    else:
        st.caption("No review record is saved for this transaction yet.")

    status_value = existing["review_status"] if existing else "Not reviewed"
    status_index = REVIEW_STATUSES.index(status_value)
    with st.form(key=f"review_form_{selected_transaction_id}"):
        review_status = st.selectbox(
            "Review status",
            options=REVIEW_STATUSES,
            index=status_index,
            key=f"review_status_{selected_transaction_id}",
        )
        st.caption(
            "Not reviewed: no review work recorded. Under review: evidence gathering or "
            "analysis is active. Reviewed: review completed. Escalated: referred for further "
            "review or investigation."
        )
        evidence_examined = st.text_area(
            "Evidence examined",
            value=existing["evidence_examined"] if existing else "",
            placeholder="For example: invoice, purchase order, approval record, or bank confirmation.",
            key=f"evidence_examined_{selected_transaction_id}",
        )
        review_conclusion = st.text_area(
            "Auditor's conclusion",
            value=existing["review_conclusion"] if existing else "",
            placeholder="Record the factual outcome of the review; do not treat a rule flag as proof.",
            key=f"review_conclusion_{selected_transaction_id}",
        )
        follow_up_action = st.text_area(
            "Recommended follow-up action",
            value=existing["follow_up_action"] if existing else "",
            placeholder="Record any follow-up, owner, or due date if applicable.",
            key=f"follow_up_action_{selected_transaction_id}",
        )
        save_review = st.form_submit_button("Save or update review record")

    if save_review:
        try:
            upsert_review_record(
                transaction_id=selected_transaction_id,
                review_status=review_status,
                evidence_examined=evidence_examined,
                review_conclusion=review_conclusion,
                follow_up_action=follow_up_action,
                database_path=review_db_path,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Review record saved. The screening result was not changed.")
            st.rerun()

st.subheader("Saved review records")
review_records = list_review_records(review_db_path)
if review_records:
    review_frame = pd.DataFrame(review_records)
    screening_columns = screened[[
        "transaction_id", "transaction_date", "vendor_id", "amount",
        "risk_score", "risk_indicators",
    ]]
    review_view = review_frame.merge(
        screening_columns, on="transaction_id", how="left", validate="one_to_one"
    )
    review_view = review_view[[
        "transaction_id", "transaction_date", "vendor_id", "amount",
        "risk_score", "risk_indicators", "review_status", "evidence_examined",
        "review_conclusion", "follow_up_action", "created_at", "updated_at",
    ]]
    st.dataframe(review_view, width="stretch", hide_index=True)
else:
    st.caption("No review records have been saved yet.")
st.download_button(
    "Download auditor review records as CSV",
    review_records_csv_bytes(review_db_path),
    "auditor_review_records.csv",
    "text/csv",
    key="download_review_records",
)
st.caption(
    "Storage note: this demo saves records in a local SQLite file. Streamlit Community Cloud "
    "does not guarantee persistence of files written while the app runs; use a secured external "
    "database before relying on review records beyond this demonstration."
)
