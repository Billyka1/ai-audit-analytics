"""Create the reproducible, fictional transaction dataset used by the demo."""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 20261023
ROWS = 1200
OUT = Path(__file__).parent / "data" / "transactions.csv"
VENDORS = [f"V{n:03d}" for n in range(1, 41)]
DEPARTMENTS = ["Operations", "Technology", "Facilities", "Marketing", "Finance"]


def main() -> None:
    rng = random.Random(SEED)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2025, 1, 1)
    records = []
    for i in range(1, ROWS + 1):
        day = start + timedelta(days=rng.randrange(365))
        # Ordinary activity is on weekdays; a small share intentionally occurs
        # on weekends so the timing rule has realistic examples to surface.
        if rng.random() < 0.07:
            if day.weekday() < 5:
                day += timedelta(days=5 - day.weekday())
        elif day.weekday() >= 5:
            day += timedelta(days=7 - day.weekday())
        hour = rng.randrange(8, 18) if rng.random() < 0.93 else rng.choice([1, 2, 3, 22, 23])
        minute = rng.randrange(60)
        amount = round(min(rng.lognormvariate(6.1, 0.8), 40000), 2)
        vendor = rng.choices(VENDORS, weights=[9 if j < 5 else 1 for j in range(40)])[0]
        records.append({
            "transaction_id": f"TX{i:05d}",
            "invoice_id": f"INV{i:05d}",
            "vendor_id": vendor,
            "transaction_date": day.replace(hour=hour, minute=minute).isoformat(sep=" "),
            "amount": amount,
            "department": rng.choice(DEPARTMENTS),
            "payment_method": rng.choice(["Bank transfer", "Card", "Cheque"]),
            "approver_id": f"EMP{rng.randrange(1, 26):03d}",
            "description": rng.choice(["Consulting services", "Office supplies", "Equipment", "Maintenance", "Software subscription"]),
        })

    # Plant known patterns for a transparent teaching demo. These labels are
    # for evaluating synthetic examples only, not real-world ground truth.
    for idx in (80, 310, 760):
        source = records[idx - 1].copy()
        duplicate = source.copy()
        duplicate["transaction_id"] = f"TX{len(records) + 1:05d}"
        duplicate["invoice_id"] = f"INV{len(records) + 1:05d}"
        records.append(duplicate)
    records[120]["amount"] = 49999.00
    records[450]["amount"] = 48750.00
    records[900]["transaction_date"] = "2025-07-19 23:47:00"
    records[1030]["transaction_date"] = "2025-10-04 02:16:00"
    # Increase concentration for one vendor while retaining realistic records.
    for rec in records[600:900]:
        rec["vendor_id"] = "V001"

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f"Wrote {len(records)} synthetic transactions to {OUT}")


if __name__ == "__main__":
    main()
