# Methodology and responsible use

## Dataset

The generator creates fictional 2025 transactions with a fixed random seed. Amounts are skewed to resemble common business payment distributions. Forty vendor IDs and five departments are used. Several records are deliberately adjusted to make each screening pattern visible in a small demo.

The CSV contains no real people, organizations, accounts, or transaction records. Synthetic examples are not a reliable proxy for a specific company's control environment.

## Rule definitions

1. **Duplicate candidate:** repeated combination of vendor ID, amount, and transaction calendar date. Exact invoice-number checks are intentionally not used because generated invoice IDs are unique.
2. **High amount:** amount greater than the chosen quantile (default 99th percentile) across all rows.
3. **Weekend:** transaction timestamp is Saturday or Sunday.
4. **After hours:** local timestamp is before 08:00 or at/after 18:00. The dataset has no timezone field.
5. **Vendor concentration:** vendor's aggregate amount divided by total transaction amount is at least the chosen threshold (default 20%).

Each row's risk score is the count of rules it triggers. Scores are not probabilities, severity ratings, or estimates of fraud likelihood. The rules are calculated on the full data before dashboard filters, so the thresholds remain stable as a user explores subsets.

## How to use a flag

Treat it as a question to investigate. Confirm the underlying transaction and source-system fields, consider timing and business context, compare supporting documents and approvals, and record the review outcome. A benign explanation may be entirely appropriate. Do not use this demo to accuse a person/vendor, make employment or payment decisions, or represent a flag as a confirmed loss.

## Limits

- Synthetic, deliberately simplified data; no external or confidential records.
- No learned model, labels, validation sample, or measured precision/recall.
- Thresholds are illustrative and should be set with domain knowledge.
- Weekend, after-hours, large-value, duplicate-looking, and concentrated spend can all be legitimate.
- Timezone, currency conversion, reversals, credit notes, invoice lifecycle, and approval hierarchies are outside scope.
- High-value cutoffs and vendor shares can shift when the underlying population changes.

## Responsible extension

Before applying similar analytics to real data, confirm access authorization, minimize personal data, preserve source lineage, document thresholds, test false positives across relevant groups and business units, and require qualified human review. Follow the organization's audit, privacy, retention, and security requirements.
