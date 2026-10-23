# AI-Powered Audit Analytics & Fraud Risk Detection

A portfolio demonstration that screens a reproducible **synthetic** transaction dataset for explainable audit-risk indicators and presents the results in an interactive dashboard.

> **Responsible use:** A flag is a potential audit-risk indicator that requires human review. It is not proof of fraud, misconduct, or error. The current application uses deterministic rules and does not contain a trained AI or machine-learning model.

## Links

- Live application: [AI Audit Analytics demo](https://ai-audit-analytics-ghqytel3bfhmnyaqwthjq7.streamlit.app/) (deployment URL supplied for this project; verify that the deployed revision matches the local files below).
- GitHub repository: [Billyka1/ai-audit-analytics](https://github.com/Billyka1/ai-audit-analytics).

The Streamlit entrypoint is `app.py`. In the current GitHub repository layout, the project files are nested under `Codex/2026-10-23/referenced-chatgpt-conversation-this-is-an/outputs/audit-analytics-project/`.

## Features

- Reproducible synthetic-data generation with seed `20261023`.
- Five transparent audit-risk screening rules.
- Date, vendor, unusual-amount percentile, and vendor-concentration controls.
- Summary metrics, flags-by-rule chart, top-vendor spend chart, and a flagged-transaction table.
- CSV download of the currently filtered and screened rows.
- An auditor review workflow for recording status, evidence examined, conclusion, and follow-up action against a stable transaction ID.
- Self-entered reviewer name or initials, review creation/update timestamps, and an append-only saved-version history.
- A saved-review table, current-review CSV export, and separate review-history CSV export, all separate from screening scores and rules.
- Human-readable indicators and responsible-use guidance.

The title keeps the portfolio identity recognizable, while the subtitle and documentation identify the current implementation as **rule-based audit risk screening and transaction analytics**.

## Technologies

- Python 3.10 or newer
- Streamlit
- pandas
- SQLite (Python standard library)
- pytest for development checks (`requirements-dev.txt`)

The deployed app uses Streamlit's built-in charts and requires no charting library beyond the Streamlit dependencies.

## Auditor review workflow

Select a flagged transaction to view its source details, screening score, and the indicators that triggered. Record one of four statuses:

- **Not reviewed:** no review work has been recorded yet.
- **Under review:** evidence gathering or analysis is active; evidence and conclusion notes may remain blank.
- **Reviewed:** review is complete; evidence examined and an auditor conclusion are required before saving.
- **Escalated:** referred for further review or investigation; evidence examined and an auditor conclusion are required before saving.

For each transaction, the app saves a stable review ID, stable `transaction_id`, self-entered reviewer name or initials, evidence examined, reviewer conclusion, recommended follow-up action, and UTC creation/update timestamps. Reviewer identity is not authenticated or verified. Saving a review does not change transaction data, screening rules, risk indicators, or `risk_score`. Updating a record preserves its review ID and original creation timestamp and appends a complete saved version to the history table. Previous versions can be inspected by transaction and exported as `auditor_review_history.csv`; current records are exported as `auditor_review_records.csv`.

### Review storage limitation

Review records and saved-version history are kept in a local SQLite file at `data/review_records.sqlite3`. On an existing database, startup adds the new reviewer/review ID columns and history table in place, retains existing rows and timestamps, assigns stable review IDs to older rows, and adds one snapshot of each legacy row as its last-known version. Earlier edits cannot be reconstructed because the old implementation did not record them. The database file is excluded from Git. You can override the path with `AUDIT_REVIEW_DB`, which is useful for tests or local setup. This public demo has no sign-in, authenticated reviewer identity, authorization, encryption, backup, or multi-user conflict management; any app visitor can add or update records. Use synthetic notes only and do not enter confidential or real audit information. Streamlit Community Cloud does not guarantee persistence of files written while an app runs, so both current records and history are demonstration-only and may be lost. Use a secured external database and proper access controls before relying on review documentation. See [Streamlit's data connection guidance](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).

## Data

The included `data/transactions.csv` contains 1,203 fictional records: 1,200 baseline transactions plus three appended duplicate-like examples. It has nine columns:

`transaction_id`, `invoice_id`, `vendor_id`, `transaction_date`, `amount`, `department`, `payment_method`, `approver_id`, and `description`.

There are 40 synthetic vendors and five departments. The generated transactions are mostly dated in 2025; weekday adjustments can move a small number into early 2026. Amounts are displayed with `$` in the UI, but the dataset has no currency-code field. The examples are demonstrations, not real fraud labels or evidence.

## Screening rules

| Indicator | Rule | Threshold behavior |
|---|---|---|
| Possible duplicate payment | Same vendor, amount, and calendar date | Every row in a matching group is flagged; invoice ID is not part of the key |
| Unusually high amount | Amount is above the selected full-dataset quantile | Strictly greater than the quantile; an equal amount is not flagged |
| Weekend transaction | Saturday or Sunday | Calendar-day rule |
| After-hours transaction | Before 08:00 or at/after 18:00 | 08:00 is in-hours; 18:00 is after-hours |
| Vendor concentration | Vendor aggregate spend share meets the selected percentage | Inclusive `>=`; no vendor is flagged if total spend is zero or negative |

The row `risk_score` is the count of triggered rules, not a fraud probability. The app calculates flags on the full dataset first, then applies the selected date and vendor filters to the displayed results. This keeps thresholds stable as users explore subsets.

## Run locally

From this folder, create a virtual environment and install the development dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
streamlit run app.py
```

On macOS or Linux, use `python3 -m venv .venv` and `source .venv/bin/activate` in place of the Windows commands.

To regenerate the included dataset:

```shell
python generate_data.py
```

To run the screening, review-storage, and dashboard smoke tests:

```shell
python -m pytest -q
```

## Reproducible default dataset results

After generation with seed `20261023`, analysis at the default 99th-percentile and 20% vendor-share thresholds gives:

- 1,203 transactions and $856,365.78 total spend.
- Three matching duplicate groups, with six individual rows flagged by the duplicate rule.
- Rule-hit counts: 6 duplicate rows, 13 high-amount rows, 93 weekend rows, 69 after-hours rows, and 403 vendor-concentration rows.
- 523 unique transactions with at least one flag and 584 total rule hits.

These are deterministic screening counts for this synthetic dataset, not model accuracy or confirmed findings.

## Limitations and next learning steps

- Synthetic and simplified data; no confidential or client records.
- No machine-learning model, labels, validated fraud outcomes, or probability estimates.
- Timing, large amounts, duplicate-looking payments, and concentrated spend can all be legitimate.
- No currency conversion, timezone normalization, reversals, invoice lifecycle, approval hierarchy, or supporting documents.
- Thresholds are illustrative and depend on the chosen population.

Possible next steps are durable external storage with authenticated reviewer identity, role-based access, backup/retention controls, and database-supported concurrency. Any anomaly-detection experiment should be separately evaluated and must not be presented as validated fraud detection without suitable labeled data and validation.
