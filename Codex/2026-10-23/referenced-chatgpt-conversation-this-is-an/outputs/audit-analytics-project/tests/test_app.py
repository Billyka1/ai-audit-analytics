from datetime import date
import json
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analysis import (
    analyze_transactions,
    dashboard_metrics,
    filter_transactions,
    rule_count_chart_data,
    vendor_spend_chart_data,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_DIR / "app.py"
DATA_PATH = PROJECT_DIR / "data" / "transactions.csv"


def test_dashboard_smoke_renders_metrics_charts_and_csv_download():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    raw = pd.read_csv(DATA_PATH)
    expected = dashboard_metrics(analyze_transactions(raw))
    assert not app.exception
    assert [metric.label for metric in app.metric] == [
        "Transactions",
        "Spend screened",
        "Transactions with flags",
        "Rule hits",
    ]
    assert [metric.value for metric in app.metric] == [
        f"{expected['transactions']:,}",
        f"${expected['spend']:,.0f}",
        f"{expected['flagged_transactions']:,}",
        f"{expected['rule_hits']:,}",
    ]
    charts = app.get("vega_lite_chart")
    assert len(charts) == 2
    flag_spec, vendor_spec = [json.loads(chart.proto.spec) for chart in charts]
    assert flag_spec["encoding"]["x"]["field"] == "rule"
    assert flag_spec["encoding"]["y"]["field"] == "transactions"
    assert vendor_spec["encoding"]["x"]["field"] == "vendor_id"
    assert vendor_spec["encoding"]["y"]["field"] == "spend"
    assert len(rule_count_chart_data(analyze_transactions(raw))) == 5
    assert len(vendor_spend_chart_data(analyze_transactions(raw))) == 12
    assert len(app.get("download_button")) == 1


def test_dashboard_filters_update_metrics_and_charts():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.date_input[0].set_value((date(2025, 1, 1), date(2025, 1, 31)))
    app.multiselect[0].set_value(["V001"])
    app.slider[0].set_value(95)
    app.slider[1].set_value(25)
    app.run()

    raw = pd.read_csv(DATA_PATH)
    analyzed = analyze_transactions(raw, amount_percentile=0.95, concentration_share=0.25)
    expected = dashboard_metrics(filter_transactions(
        analyzed, (date(2025, 1, 1), date(2025, 1, 31)), ["V001"]
    ))
    assert not app.exception
    assert app.metric[0].value == f"{expected['transactions']:,}"
    assert app.metric[1].value == f"${expected['spend']:,.0f}"
    assert app.metric[2].value == f"{expected['flagged_transactions']:,}"
    assert app.metric[3].value == f"{expected['rule_hits']:,}"
    assert len(app.get("vega_lite_chart")) == 2


@pytest.mark.parametrize("filter_name", ["date", "vendor", "amount", "concentration"])
def test_each_dashboard_filter_updates_metrics(filter_name):
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    raw = pd.read_csv(DATA_PATH)
    date_range = None
    vendors = None
    percentile = 0.99
    concentration = 0.20

    if filter_name == "date":
        date_range = (date(2025, 1, 1), date(2025, 1, 31))
        app.date_input[0].set_value(date_range)
    elif filter_name == "vendor":
        vendors = ["V001"]
        app.multiselect[0].set_value(vendors)
    elif filter_name == "amount":
        percentile = 1.0
        app.slider[0].set_value(100)
    elif filter_name == "concentration":
        concentration = 0.50
        app.slider[1].set_value(50)

    app.run()
    analyzed = analyze_transactions(raw, percentile, concentration)
    expected = dashboard_metrics(filter_transactions(analyzed, date_range, vendors))
    assert not app.exception
    assert [metric.value for metric in app.metric] == [
        f"{expected['transactions']:,}",
        f"${expected['spend']:,.0f}",
        f"{expected['flagged_transactions']:,}",
        f"{expected['rule_hits']:,}",
    ]


def test_dashboard_empty_vendor_selection_is_safe():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.multiselect[0].set_value([])
    app.run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["0", "$0", "0", "0"]
    assert len(app.get("download_button")) == 1
