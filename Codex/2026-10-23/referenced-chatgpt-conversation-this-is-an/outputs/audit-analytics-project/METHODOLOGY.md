# Methodology and responsible use

## Purpose and scope

This portfolio application demonstrates transparent transaction screening on fictional data. It supports exploration and human follow-up. It does not determine fraud, misconduct, error, intent, or loss, and it is not a production audit control.

## Synthetic dataset assumptions

`generate_data.py` creates 1,200 baseline transactions using fixed seed `20261023`, then adds three copies to create duplicate-like examples. The CSV has transaction and invoice IDs, vendor ID, timestamp, amount, department, payment method, approver ID, and description. It contains no real people, organizations, accounts, or transaction records.

Most dates begin in 2025. Weekend-to-weekday adjustments can move some records into early 2026. Amounts are synthetic, skewed, and capped for ordinary records; two larger examples are planted to exercise the amount rule. A vendor assignment block creates a concentrated-spend example. The CSV does not include currency or timezone fields; the interface's `$` format is illustrative.

The generator checks that baseline `(vendor_id, amount, calendar date)` signatures are unique before appending the intended duplicate examples. Each appended row receives a new transaction and invoice ID while preserving the source vendor, amount, and timestamp. The matching rule flags each row in a duplicate group, not only the copied row.

## Screening rules

All thresholds are applied to the analyzed full dataset before dashboard date/vendor filters are applied.

1. **Possible duplicate payment:** Rows share the same `vendor_id`, numeric `amount`, and calendar date. Time of day, transaction ID, and invoice ID are not compared. Every row in a repeated group is flagged. Different vendor, amount, or date prevents a match.
2. **Unusually high amount:** The threshold is pandas' quantile for the selected percentile (default 0.99). A row is flagged only when `amount > threshold`; equality is not flagged. The slider ranges from the 90th through 100th percentile.
3. **Weekend transaction:** The parsed transaction timestamp has day-of-week Saturday or Sunday (`dayofweek >= 5`). Monday is not flagged by this rule.
4. **After-hours transaction:** The parsed local timestamp is before 08:00 or at/after 18:00. Exactly 08:00 and 17:59 are in-hours; exactly 18:00 is after-hours. Timezone conversion is not performed.
5. **Vendor concentration:** For each row, vendor total spend is divided by total spend across all rows. A row is flagged when the share is greater than or equal to the selected threshold (default 0.20). Equality is included. When total spend is zero or negative, shares are set to zero and no vendor concentration flags are assigned. Concentration is a contextual screening indicator, not inherently suspicious.

The analysis function validates both thresholds are between 0 and 1 inclusive.

## Auditor review workflow

The review workflow documents follow-up after screening; it does not change the screening logic or risk score. The reviewer selects a flagged row, sees the original transaction details and current rule indicators, and saves a separate record keyed by the stable `transaction_id`.

Each review record contains:

- **Review ID:** a stable UUID generated once for the review record and retained on updates.
- **Reviewer identity:** a name or initials entered by the user. It is not authenticated or independently verified.
- **Review status:** `Not reviewed`, `Under review`, `Reviewed`, or `Escalated`.
- **Evidence examined:** factual descriptions of source records or other evidence considered.
- **Reviewer conclusion:** the auditor's documented outcome; it is not treated as a fraud label.
- **Recommended follow-up action:** additional audit steps, referral, or other action, where applicable.
- **Created and updated timestamps:** UTC ISO 8601 timestamps with an explicit `+00:00` offset. Creation time is retained when the record is updated; update time changes on each save.

`Not reviewed` means no work has been recorded. `Under review` means evidence gathering or analysis is active; evidence and conclusion fields can be blank. `Reviewed` means the review is complete, and `Escalated` means it was referred for further review or investigation. Both completed statuses require non-empty evidence and a conclusion; if no evidence was available, the reviewer should document that fact. Follow-up action is optional.

Review records are stored in SQLite in `data/review_records.sqlite3`, independently of `analysis.py`. Saving or updating a review never writes to `transactions.csv`, changes a screening flag, or modifies `risk_score`. The current screening score and indicators shown beside saved review records are recalculated from current rule settings; review history does not snapshot the past threshold configuration.

Each save appends a row to `review_history` with the review ID, transaction ID, self-entered reviewer identity, previous status, status after the save, evidence examined, conclusion, follow-up action, and UTC change timestamp. Each history row contains the complete saved version, so earlier notes remain inspectable after later updates. The initial save is also recorded as the first version, with no previous status. Current reviews are exported to `auditor_review_records.csv`; saved versions are exported to `auditor_review_history.csv`. Both CSVs include headers when empty.

For optional persistence outside Streamlit Community Cloud's local filesystem, setting `AUDIT_REVIEW_DATABASE_URL` switches the same storage functions to managed PostgreSQL. The implementation uses `psycopg` and a process-level pool of up to four connections, parameterized statements, and requires TLS (`sslmode=require` or stronger). Local use can provide the URL using `.streamlit/secrets.toml`; Community Cloud can provide it in app Settings → Secrets. The URL is never hardcoded or committed. The dashboard remains available if the external database is not ready, while review actions and exports are disabled with an error message.

Schema initialization uses `CREATE TABLE IF NOT EXISTS` and adds missing columns to the existing SQLite table rather than replacing the database. Existing rows retain their transaction IDs, review fields, and timestamps; each receives a stable review ID. Migration adds one last-known snapshot for each legacy review using its prior `updated_at` timestamp and blank reviewer identity, since the older implementation did not collect identity. Earlier changes cannot be reconstructed, but this baseline preserves each legacy record before its next update.

The reviewer identity is a user-entered label only. This public app has no sign-in, so any visitor can enter any name or initials and create or update records; the application does not verify who made a change. It has no role-based access, encryption policy, or production privacy controls. Use synthetic notes only. The SQLite file is excluded from Git. Streamlit Community Cloud does not guarantee persistence of local files generated while the app runs, so SQLite use there is demonstration-only and records/history may disappear after platform lifecycle events. Neon is the recommended simple managed PostgreSQL choice for this portfolio because Streamlit documents its setup; Supabase is another managed PostgreSQL option. Current free-tier limits may include compute, inactivity pauses, restricted restore history, and no scheduled backups. Check provider terms before use; no backup or restore process is implemented by this app. See [Streamlit data connection guidance](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data), [Streamlit Neon tutorial](https://docs.streamlit.io/develop/tutorials/databases/neon), [Neon pricing](https://neon.com/pricing), and [Supabase pricing](https://supabase.com/pricing).

`migrate_review_store.py` copies current SQLite reviews and saved history to PostgreSQL in a transaction, preserves stable IDs and timestamp strings, rejects conflicting destination records instead of overwriting, and verifies each source row before commit. It never deletes the SQLite source. Migration requires an actual configured database URL. At the time of this change, the inspected repository had no `data/review_records.sqlite3`, so there was no existing local review database to migrate. The code has not been connected to or verified against a provider database; its presence must not be represented as proof of persistence. This feature demonstrates an application-level change log; it is not tamper-proof or a legally reliable audit trail. Do not use it for real audit evidence. Durable audit documentation requires secured persistent storage, verified identities, access controls, backup/retention procedures, and appropriate governance.

## Risk score and dashboard counts

`risk_score` is the integer count of the five Boolean rules triggered by that row. `risk_indicators` lists each triggered rule's label, or `No rule-based flags`. A score of 3 means three rules triggered; it is not a probability, calibrated risk rating, or severity score.

The dashboard's **Transactions with flags** metric counts unique rows where `risk_score > 0`. **Rule hits** sums all rule flags, so one transaction may add several hits while counting once in the unique flagged-transaction metric. Date/vendor filtering is applied after rule calculation; metrics, charts, table, and CSV then describe the filtered rows.

For the regenerated seed-`20261023` dataset at the default settings, there are 1,203 rows, $856,365.78 total spend, three duplicate groups (six duplicate-flagged rows), 13 high-amount flags, 93 weekend flags, 69 after-hours flags, 403 vendor-concentration flags, 523 unique flagged rows, and 584 total rule hits. These are screening results for this synthetic dataset only.

## Interpretation and limits

- A flag prompts a question; it is not proof of fraud, a confirmed exception, or a validated fraud prediction.
- Review source records, supporting documents, approvals, timing, business context, and applicable controls. Record the human review outcome.
- The dataset is deliberately synthetic. It has no fraud labels, validation set, measured precision/recall, or trained model.
- Duplicate-like rows may be legitimate; the matching rule is intentionally simple and does not compare invoice IDs.
- High values, weekend or after-hours timestamps, and vendor concentration may all have valid operational explanations.
- No currency conversion, timezone normalization, reversals, credit notes, invoice lifecycle, or approval hierarchy is modeled.
- Thresholds depend on the population and can shift if the dataset changes.

The new reviewer fields are documentation for a synthetic portfolio demonstration, not a full case-management or audit-evidence repository. The app does not verify evidence or adjudicate the reviewer's conclusion.

Before adapting similar analytics to real data, confirm access authorization, minimize personal data, preserve source lineage, document threshold selection, assess false positives, and require qualified human review under the organization's audit, privacy, retention, and security requirements.
