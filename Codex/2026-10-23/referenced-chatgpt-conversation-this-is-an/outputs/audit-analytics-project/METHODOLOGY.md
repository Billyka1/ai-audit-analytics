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
- No currency conversion, timezone normalization, reversals, credit notes, invoice lifecycle, approval hierarchy, or reviewer-disposition workflow is modeled.
- Thresholds depend on the population and can shift if the dataset changes.

Before adapting similar analytics to real data, confirm access authorization, minimize personal data, preserve source lineage, document threshold selection, assess false positives, and require qualified human review under the organization's audit, privacy, retention, and security requirements.
