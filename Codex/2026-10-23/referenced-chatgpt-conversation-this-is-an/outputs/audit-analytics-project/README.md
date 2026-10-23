# AI-Powered Audit Analytics & Fraud Risk Detection

A beginner-friendly portfolio project that screens **fictional** financial transactions for explainable audit-risk indicators and presents them in an interactive dashboard.

> **Important:** A flag is a risk indicator for human follow-up. It is not proof of fraud, misconduct, or error. The data is synthetic and must not be presented as real client evidence.

## What it demonstrates

- Reproducible synthetic data generation (seed: `20261023`).
- Data analysis with five transparent screening rules.
- Interactive filters, summary metrics, charts, flagged records, and CSV export.
- A clear distinction between a rule-based risk score and a fraud conclusion.

This first version does not train a machine-learning model. “AI-powered” describes the portfolio direction; the implemented baseline is deliberately explainable and suitable for learning. A later extension could compare these rules with an anomaly-detection model.

## Start the dashboard

You need Python 3.10 or newer.

1. Open a terminal in this project folder.
2. Create and activate an environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   On macOS or Linux use `python3 -m venv .venv` and `source .venv/bin/activate`.

3. Install packages and launch:

   ```shell
   python -m pip install -r requirements.txt
   streamlit run app.py
   ```

The browser opens the dashboard. The included CSV makes the first run immediate.

## Rebuild the data

```shell
python generate_data.py
```

The generator creates 1,203 transactions: 1,200 baseline records and three intentional duplicate examples, alongside planted high amounts and unusual timestamps. Those examples help demonstrate rule behavior; they are not real fraud labels.

## Risk rules

| Indicator | Screening rule | Why a reviewer may follow up |
|---|---|---|
| Possible duplicate payment | Same vendor, amount, and date appears more than once | Could represent a duplicate, split, recurring, or legitimate repeat payment |
| Unusually high amount | Amount exceeds a selected percentile of the dataset | May merit comparison with approval limits, contract terms, and prior activity |
| Weekend transaction | Saturday or Sunday timestamp | May be normal in some operations; compare with business context |
| After-hours transaction | Before 08:00 or at/after 18:00 | Check authorization, posting time, and system batch behavior |
| Vendor concentration | Vendor spend is at least the selected share of total spend | Concentration can create dependency or sourcing risk; it is not inherently improper |

The dashboard lets reviewers adjust the percentile and concentration threshold. Changing date/vendor filters changes the displayed population; rules are calculated over the full dataset first so that thresholds remain stable while browsing.

## Project files

- `app.py` — interactive Streamlit dashboard.
- `analysis.py` — screening rules and explanations.
- `generate_data.py` — deterministic synthetic data generator.
- `data/transactions.csv` — included demo dataset.
- `METHODOLOGY.md` — assumptions, limits, and review guidance.

## Suggested portfolio description

“Built an explainable audit analytics dashboard in Python that screens a reproducible synthetic transaction dataset for duplicate-payment candidates, high-value outliers, unusual timing, and vendor spend concentration. Designed the output as human-review indicators rather than automated fraud findings.”

## Next learning steps

1. Add unit tests for each rule and boundary conditions.
2. Add transaction-level and vendor-level trend charts.
3. Compare rule flags with Isolation Forest on the synthetic data, explaining model limits.
4. Add reviewer disposition fields and an audit trail.

## License

MIT. See `LICENSE`.
