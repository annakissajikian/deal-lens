"""
Real-deal regression test: Microsoft / Activision Blizzard (announced 18 Jan 2022).

Every input comes from data/sample_deals/microsoft_activision.json, where each
figure has its document, section, page and snippet under "_sources".

Hand calculation (USD millions, shares in millions)
---------------------------------------------------
Share build (Merger Agreement s.3.7, 13 Jan 2022; strike from 10-K Note 16)
RSUs / PSUs           = 8.717050 + 4.424740                  =  13.141790
Option proceeds       = 9.083202 × 57.77                     = 524.7366
Shares repurchased    = 524.7366 / 95.00                     =   5.523543
Net option shares     = 9.083202 − 5.523543                  =   3.559659
Fully diluted shares  = 779.057360 + 3.559659 + 13.141790    = 795.758809

Transaction value
Equity value          = 95.00 × 795.758809                   = 75,597.09
Net debt              = 3,650 − 10,423                       = −6,773     (net cash)
Enterprise value      = 75,597.09 + 3,650 − 10,423           = 68,824.09
  vs headline 68,700 ("inclusive of net cash")               = +0.18%

Premium
Premium               = 95.00 / 65.39 − 1                    = 45.28%     (proxy: "approximately 45.3%")
Unaffected equity     = 65.39 × 795.758809                   = 52,034.67
Premium paid          = 75,597.09 − 52,034.67                = 23,562.42
Unaffected EV         = 52,034.67 − 6,773                    = 45,261.67  -> 13.41x EBITDA

Multiples and profitability (FY2021)
EBITDA                = 3,259 + 116                          = 3,375
EV / Revenue          = 68,824.09 / 8,803                    = 7.82x
EV / EBITDA           = 68,824.09 / 3,375                    = 20.39x
EV / EBIT             = 68,824.09 / 3,259                    = 21.12x
Equity / Net income   = 75,597.09 / 2,699                    = 28.01x
EBITDA margin         = 3,375 / 8,803                        = 38.34%

Synergies are zero (none disclosed), so pro forma EBITDA = 3,375 and the
synergy-adjusted multiple equals EV / EBITDA. Financing is 100% cash.

DCF (management UFCF 2022E–2026E, WACC 7.25%, g 2.50%, valued at 31 Dec 2021)
PV of FCF      = 1,768/1.0725 + 3,387/1.0725^2 + 3,396/1.0725^3 + 3,773/1.0725^4 + 3,886/1.0725^5
               = 1,648.48 + 2,944.56 + 2,752.81 + 2,851.66 + 2,738.52   = 12,936.03
Terminal value = 3,886 × 1.025 / (0.0725 − 0.025) = 3,983.15 / 0.0475   = 83,855.79
PV of TV       = 83,855.79 × 1/1.0725^5 (0.704715)                     = 59,094.43
DCF EV         = 12,936.03 + 59,094.43                                  = 72,030.46
DCF equity     = 72,030.46 − (−6,773)                                   = 78,803.46
Per share      = 78,803.46 / 795.758809                                 = $99.03
TV share 82.0%; offer $95.00 is 4.07% below the DCF value.
Heatmap corners: WACC 8.00% / g 2.25% = $83.52; WACC 6.50% / g 2.75% = $122.79
(Allen & Company, same ranges: $84.73 – $123.87).
"""

import json
from pathlib import Path

import pytest

from finance.dcf import analyse_dcf
from finance.transaction import analyse_transaction
from utils.io import load_deal

DEAL_FILE = Path(__file__).parent.parent / "data" / "sample_deals" / "microsoft_activision.json"
RAW = json.loads(DEAL_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def r():
    return analyse_transaction(load_deal(DEAL_FILE))


# ------------------------------------------------ inputs built from filings --

def test_ebitda_is_operating_income_plus_da():
    # 10-K: operating income 3,259 (F-4) + depreciation and amortization 116 (F-6)
    assert RAW["facts"]["ebitda"] == 3_259 + 116


def test_rsus_are_time_vesting_plus_psus_at_target():
    # Merger Agreement s.3.7(c): 8,717,050 time-vesting + 4,424,740 performance-vesting at target
    assert RAW["facts"]["share_build"]["rsus"] == pytest.approx(8.717050 + 4.424740, abs=1e-9)


def test_every_fact_has_a_source():
    sources = RAW["_sources"]
    facts = {k for k in RAW["facts"] if k != "share_build"}
    build = {f"share_build.{k}" for k in ("basic_shares", "rsus")}
    build |= {f"share_build.option_tranches[{i}].{k}"
              for i in range(len(RAW["facts"]["share_build"]["option_tranches"]))
              for k in ("number", "strike")}
    missing = sorted((facts | build) - set(sources) - {"financials_period"})
    assert not missing, f"facts without a _sources entry: {missing}"


# ------------------------------------------------------------ share count --

def test_share_count(r):
    assert r.value("basic_shares") == pytest.approx(779.057360)
    assert r.value("options_exercised") == pytest.approx(9.083202)
    assert r.value("shares_repurchased") == pytest.approx(5.523543, abs=1e-6)
    assert r.value("net_option_shares") == pytest.approx(3.559659, abs=1e-6)
    assert r.value("rsus") == pytest.approx(13.141790)
    assert r.value("fully_diluted_shares") == pytest.approx(795.758809, abs=1e-6)


# -------------------------------------------------------- transaction value --

def test_transaction_value(r):
    assert r.value("equity_value") == pytest.approx(75_597.09, abs=0.01)
    assert r.value("net_debt") == pytest.approx(-6_773)
    assert r.value("enterprise_value") == pytest.approx(68_824.09, abs=0.01)


def test_enterprise_value_matches_headline_within_tolerance(r):
    # Microsoft: "$68.7 billion, inclusive of Activision Blizzard's net cash" -> compare with EV
    check = RAW["_cross_checks"]["headline_transaction_value"]
    assert check["compare_to"] == "enterprise_value"
    gap = r.value("enterprise_value") / check["value"] - 1
    assert gap == pytest.approx(0.0018, abs=1e-4)              # +0.18%
    assert abs(gap) <= check["tolerance"]                      # within 2%


def test_headline_is_not_equity_value(r):
    # Equity value (75,597) is ~10% above the headline: using it as stated_equity_value would be wrong
    assert r.value("equity_value") / RAW["_cross_checks"]["headline_transaction_value"]["value"] - 1 > 0.09


# ------------------------------------------------------------------ premium --

def test_premium_matches_proxy(r):
    assert r.value("premium") == pytest.approx(0.452822, abs=1e-6)
    assert round(r.value("premium"), 3) == RAW["_cross_checks"]["proxy_premium"]["value"]   # 45.3%
    assert r.value("unaffected_equity_value") == pytest.approx(52_034.67, abs=0.01)
    assert r.value("premium_paid") == pytest.approx(23_562.42, abs=0.01)
    assert r.value("unaffected_ev_ebitda") == pytest.approx(13.41, abs=0.005)


# ------------------------------------------------ multiples and profitability --

def test_multiples(r):
    assert r.value("ev_revenue") == pytest.approx(7.82, abs=0.005)
    assert r.value("ev_ebitda") == pytest.approx(20.39, abs=0.005)
    assert r.value("ev_ebit") == pytest.approx(21.12, abs=0.005)
    assert r.value("pe") == pytest.approx(28.01, abs=0.005)
    assert r.value("ebitda_margin") == pytest.approx(0.3834, abs=0.00005)


def test_zero_synergies_and_all_cash(r):
    assert r.value("pro_forma_ebitda") == pytest.approx(3_375)
    assert r.value("synergy_adj_ev_ebitda") == pytest.approx(r.value("ev_ebitda"))
    assert r.value("financed_cash") == pytest.approx(r.value("equity_value"))
    assert r.value("financed_debt") == 0 and r.value("financed_stock") == 0


def test_expected_warnings_only(r):
    # stated_equity_value is deliberately empty and tax_rate is not provided; nothing else is flagged
    assert len(r.warnings) == 2
    joined = " ".join(r.warnings)
    assert "stated_equity_value" in joined and "tax_rate" in joined


# ---------------------------------------------------------------------- DCF --

@pytest.fixture(scope="module")
def dcf():
    return analyse_dcf(load_deal(DEAL_FILE))


def test_dcf_inputs_are_the_proxy_forecast():
    d = RAW["dcf"]
    assert d["unlevered_fcf"] == [1768.0, 3387.0, 3396.0, 3773.0, 3886.0]       # proxy p.51, 2022E–2026E
    assert d["wacc"] == pytest.approx((0.065 + 0.08) / 2)                     # Allen & Co midpoint
    assert d["terminal_growth"] == pytest.approx((0.0225 + 0.0275) / 2)
    assert all(f"dcf.{k}" in RAW["_sources"] for k in ("unlevered_fcf", "wacc", "terminal_growth"))


def test_dcf_valuation(dcf):
    assert dcf.value("pv_forecast_fcf") == pytest.approx(12_936.03, abs=0.01)
    assert dcf.value("terminal_value") == pytest.approx(83_855.79, abs=0.01)
    assert dcf.value("pv_terminal_value") == pytest.approx(59_094.43, abs=0.01)
    assert dcf.value("dcf_enterprise_value") == pytest.approx(72_030.46, abs=0.01)
    assert dcf.value("dcf_equity_value") == pytest.approx(78_803.46, abs=0.01)
    assert dcf.value("dcf_value_per_share") == pytest.approx(99.03, abs=0.005)
    assert dcf.value("tv_share_of_ev") == pytest.approx(0.8204, abs=0.0001)
    assert dcf.value("offer_vs_dcf") == pytest.approx(-0.0407, abs=0.0001)


def test_dcf_range_close_to_allen_and_company(dcf):
    low, high = dcf.grid_range()
    assert low == pytest.approx(83.52, abs=0.005) and high == pytest.approx(122.79, abs=0.005)
    allen = RAW["_cross_checks"]["allen_dcf_range"]
    assert abs(low / allen["low"] - 1) < 0.02 and abs(high / allen["high"] - 1) < 0.02   # within 2%


def test_dcf_warns_that_terminal_value_dominates(dcf):
    assert dcf.warnings == ["Terminal value is 82% of DCF enterprise value: the valuation depends mostly on "
                            "the perpetuity assumptions (WACC and g)."]
