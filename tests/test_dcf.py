"""
Step 4 tests: DCF valuation and WACC × terminal-growth sensitivity.

Hand calculation (illustrative deal facts: net debt 1,200 − 400 = 800, 100m shares, offer $60)
----------------------------------------------------------------------------------------------
Forecast FCF 400, 440, 484 (grows 10% a year) · WACC 10% · g 2%
PV year 1 = 400 / 1.10       = 363.636364
PV year 2 = 440 / 1.10^2     = 363.636364
PV year 3 = 484 / 1.10^3     = 363.636364   (FCF grows at the discount rate, so every PV is equal)
Σ PV of forecast FCF         = 1,090.909091
Terminal value = 484 × 1.02 / (0.10 − 0.02) = 493.68 / 0.08 = 6,171.00
PV of terminal value = 6,171 / 1.331        = 4,636.363636
DCF EV      = 1,090.909091 + 4,636.363636   = 5,727.272727
DCF equity  = 5,727.272727 − 800            = 4,927.272727
Per share   = 4,927.272727 / 100            = 49.272727
TV share of EV = 4,636.363636 / 5,727.272727 = 80.95%    (> 75% -> warning)
Offer vs DCF   = 60 / 49.272727 − 1          = +21.77%

Sensitivity cell WACC 11%, g 2%:
PV = 400/1.11 + 440/1.11^2 + 484/1.11^3 = 360.3604 + 357.1139 + 353.8966 = 1,071.3709
TV = 484 × 1.02 / 0.09 = 5,485.3333 -> PV 5,485.3333 / 1.367631 = 4,010.8285
EV = 5,082.1993 -> per share (5,082.1993 − 800) / 100 = 42.821993
"""

from dataclasses import replace

import pytest

from finance.dcf import (analyse_dcf, dcf_enterprise_value, default_axis, discount_factor,
                         present_values, terminal_value, value_per_share)
from finance.models import DCFInputs, DealInputError
from finance.transaction import analyse_transaction
from finance.validation import validate
from tests.test_transaction import DEAL
from tests.test_validation import sample_dict, write
from utils.io import load_deal

FCF = (400.0, 440.0, 484.0)
DCF = DCFInputs(forecast_years=(2026, 2027, 2028), unlevered_fcf=FCF, wacc=0.10, terminal_growth=0.02,
                valuation_date="2025-12-31")

def deal_with_dcf(**changes):
    return replace(DEAL, dcf=replace(DCF, **changes))

@pytest.fixture
def r():
    return analyse_dcf(deal_with_dcf())

# --------------------------------------------------------- single formulas --

def test_discounting():
    assert discount_factor(0.10, 1) == pytest.approx(1 / 1.10)
    assert present_values(FCF, 0.10) == pytest.approx([363.636364] * 3)

def test_terminal_value():
    assert terminal_value(484, 0.10, 0.02) == pytest.approx(6_171.0)
    assert terminal_value(484, 0.02, 0.02) is None           # WACC = g: formula undefined
    assert terminal_value(484, 0.02, 0.03) is None           # WACC < g
    assert terminal_value(-50, 0.10, 0.02) is None           # negative final FCF: not meaningful

def test_enterprise_value_and_per_share():
    ev = dcf_enterprise_value(FCF, 0.10, 0.02)
    assert ev == pytest.approx(5_727.272727)
    assert value_per_share(ev, 800, 100) == pytest.approx(49.272727)
    assert value_per_share(None, 800, 100) is None

def test_default_axis():
    assert default_axis(0.10, 0.005, 2) == (0.09, 0.095, 0.10, 0.105, 0.11)

# ---------------------------------------------------------- full analysis --

def test_dcf_metrics(r):
    assert r.value("pv_forecast_fcf") == pytest.approx(1_090.909091)
    assert r.value("terminal_value") == pytest.approx(6_171.0)
    assert r.value("pv_terminal_value") == pytest.approx(4_636.363636)
    assert r.value("dcf_enterprise_value") == pytest.approx(5_727.272727)
    assert r.value("dcf_equity_value") == pytest.approx(4_927.272727)
    assert r.value("dcf_value_per_share") == pytest.approx(49.272727)
    assert r.value("tv_share_of_ev") == pytest.approx(0.809524, abs=1e-6)
    assert r.value("offer_vs_dcf") == pytest.approx(0.217712, abs=1e-6)

def test_every_dcf_metric_depends_on_assumptions(r):
    assert all(m.depends_on_assumptions and m.section == "DCF" for m in r.metrics.values())

def test_schedule(r):
    assert [row["year"] for row in r.schedule] == [2026, 2027, 2028]
    assert [row["pv"] for row in r.schedule] == pytest.approx([363.636364] * 3)
    assert r.schedule[2]["discount_factor"] == pytest.approx(1 / 1.331)

def test_sensitivity_grid(r):
    assert r.wacc_axis == (0.09, 0.095, 0.10, 0.105, 0.11)
    assert r.growth_axis == (0.015, 0.0175, 0.02, 0.0225, 0.025)
    assert r.grid[2][2] == pytest.approx(49.272727)            # base case in the centre
    assert r.grid[4][2] == pytest.approx(42.821993)            # WACC 11%, g 2%
    assert r.grid_offer_vs[2][2] == pytest.approx(0.217712, abs=1e-6)   # 60 / 49.272727 − 1
    assert r.grid_offer_vs[4][2] == pytest.approx(60 / 42.821993 - 1)
    # higher WACC -> lower value; higher growth -> higher value
    assert all(r.grid[i][2] > r.grid[i + 1][2] for i in range(4))
    assert all(r.grid[2][j] < r.grid[2][j + 1] for j in range(4))

def test_custom_axes_and_undefined_cells():
    r = analyse_dcf(deal_with_dcf(wacc_range=(0.02, 0.10), growth_range=(0.02,)))
    assert r.grid[0][0] is None                                # WACC = g -> n.m.
    assert r.grid[1][0] == pytest.approx(49.272727)

def test_no_dcf_inputs_gives_none():
    assert analyse_dcf(DEAL) is None

def test_transaction_outputs_unchanged_by_dcf():
    assert analyse_transaction(deal_with_dcf()).value("enterprise_value") == pytest.approx(6_800)

# ---------------------------------------------------------------- warnings --

def test_warnings(r):
    assert any("Terminal value is 81% of DCF enterprise value" in w for w in r.warnings)
    high = analyse_dcf(deal_with_dcf(terminal_growth=0.05, wacc=0.12)).warnings
    assert any("Terminal growth (5.00%) is above 4%" in w for w in high)
    assert any("WACC (3.00%) is outside" in w for w in analyse_dcf(deal_with_dcf(wacc=0.03, terminal_growth=0.01)).warnings)

def test_negative_final_fcf_is_nm_with_warning():
    r = analyse_dcf(deal_with_dcf(unlevered_fcf=(400.0, 440.0, -10.0)))
    assert r.value("dcf_enterprise_value") is None and r.value("dcf_value_per_share") is None
    assert any("Final-year free cash flow is not positive" in w for w in r.warnings)

# ------------------------------------------------------------------ errors --

@pytest.mark.parametrize("changes, expected", [
    ({"wacc": 0.02}, "dcf.wacc must be greater than dcf.terminal_growth"),
    ({"wacc": 8.0}, "dcf.wacc must be a decimal between 0 and 1"),
    ({"terminal_growth": 2.5}, "dcf.terminal_growth must be a decimal"),
    ({"wacc": float("nan")}, "dcf.wacc must be a finite number"),
    ({"forecast_years": ()}, "dcf.forecast_years must be a non-empty list"),
    ({"forecast_years": (2026, 2028, 2029)}, "consecutive and increasing"),
    ({"forecast_years": (2026.0, 2027.0, 2028.0)}, "whole years"),
    ({"unlevered_fcf": (400.0, 440.0)}, "one value per forecast year (3 years, 2 values)"),
    ({"unlevered_fcf": (400.0, None, 484.0)}, "only finite numbers"),
    ({"wacc_range": (0.08, 9.0)}, "dcf.wacc_range must be a list of decimals"),
])
def test_rejects_bad_dcf_inputs(changes, expected):
    with pytest.raises(DealInputError) as exc:
        validate(deal_with_dcf(**changes))
    assert any(expected in e for e in exc.value.errors)

def test_dcf_errors_reported_with_other_errors():
    bad = replace(deal_with_dcf(wacc=0.02), facts=replace(DEAL.facts, revenue=-1))
    with pytest.raises(DealInputError) as exc:
        validate(bad)
    joined = " ".join(exc.value.errors)
    assert "revenue cannot be negative" in joined and "dcf.wacc must be greater" in joined

# ------------------------------------------------------------- JSON loading --

def test_loader_reads_dcf_section(tmp_path):
    data = sample_dict()
    data["dcf"] = {"forecast_years": [2026, 2027, 2028], "unlevered_fcf": FCF, "wacc": 0.10,
                   "terminal_growth": 0.02, "valuation_date": "2025-12-31", "_source": "ignored"}
    deal = load_deal(write(tmp_path, data))
    assert deal.dcf == DCF

@pytest.mark.parametrize("bad, expected", [
    ([1, 2], "Section 'dcf' must be an object"),
    ({"forecast_years": "2026", "unlevered_fcf": [1], "wacc": 0.1, "terminal_growth": 0.02},
     "dcf.forecast_years must be a list"),
    ({"forecast_years": [2026], "unlevered_fcf": [1], "wacc": 0.1, "terminal_growth": 0.02, "wac": 1},
     "Unknown field in 'dcf': 'wac'"),
])
def test_loader_rejects_malformed_dcf(tmp_path, bad, expected):
    data = sample_dict()
    data["dcf"] = bad
    with pytest.raises(DealInputError, match=expected):
        load_deal(write(tmp_path, data))
