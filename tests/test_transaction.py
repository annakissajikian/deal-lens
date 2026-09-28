"""
Finance tests: are the numbers right?

Hand calculation for the illustrative deal
------------------------------------------
Equity value      = 60 × 100                 = 6,000
Net debt          = 1,200 − 400              =   800
Enterprise value  = 6,000 + 1,200 − 400      = 6,800
Premium           = 60 / 50 − 1              = 20%
Unaffected equity = 50 × 100                 = 5,000   -> premium paid 1,000
Unaffected EV     = 5,000 + 800              = 5,800   -> 11.60x EBITDA
EV / Revenue      = 6,800 / 2,500            = 2.72x
EV / EBITDA       = 6,800 / 500              = 13.60x
EV / EBIT         = 6,800 / 400              = 17.00x
Equity / NI       = 6,000 / 300              = 20.00x
EBITDA margin     = 500 / 2,500              = 20%
Rev. syn. EBITDA  = 100 × 30%                = 30
Total synergies   = 50 + 30                  = 80      -> after tax (25%) 60
Pro forma EBITDA  = 500 + 50 + 30            = 580
Syn-adj EV/EBITDA = 6,800 / 580              = 11.72x
Financing         = 6,000 × 40% / 40% / 20%  = 2,400 / 2,400 / 1,200
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from finance.models import DealAssumptions, DealFacts, DealInfo, DealInputs
from finance.transaction import (acquisition_premium, analyse_transaction, enterprise_value,
                                 equity_value, multiple)
from utils.io import load_deal

SAMPLE = Path(__file__).parent.parent / "data" / "sample_deals" / "illustrative_deal.json"

FACTS = DealFacts(offer_price_per_share=60, unaffected_share_price=50, diluted_shares_outstanding=100,
                  revenue=2_500, ebitda=500, ebit=400, net_income=300, total_debt=1_200, cash=400,
                  stated_equity_value=6_000)
ASSUMPTIONS = DealAssumptions(cost_synergies=50, revenue_synergies=100,
                              revenue_synergy_incremental_margin=0.30,
                              financing_cash=0.4, financing_debt=0.4, financing_stock=0.2, tax_rate=0.25)
DEAL = DealInputs(DealInfo("Northwind Holdings", "Apex Components", "Industrials", date(2026, 1, 15)),
                  FACTS, ASSUMPTIONS)


def deal_with(facts=None, assumptions=None) -> DealInputs:
    """Copy of DEAL with some facts/assumptions changed."""
    return DealInputs(DEAL.info,
                      replace(FACTS, **(facts or {})),
                      replace(ASSUMPTIONS, **(assumptions or {})))


@pytest.fixture
def r():
    return analyse_transaction(DEAL)


# --------------------------------------------------------- single formulas --

def test_formula_functions():
    assert equity_value(60, 100) == 6_000
    assert enterprise_value(6_000, 1_200, 400) == 6_800
    assert acquisition_premium(60, 50) == pytest.approx(0.20)
    assert multiple(6_800, 500) == pytest.approx(13.6)
    assert multiple(6_800, 0) is None
    assert multiple(6_800, -10) is None
    assert multiple(6_800, None) is None


# ---------------------------------------------------------- full analysis --

def test_transaction_value(r):
    assert r.value("equity_value") == pytest.approx(6_000)
    assert r.value("net_debt") == pytest.approx(800)
    assert r.value("enterprise_value") == pytest.approx(6_800)


def test_premium(r):
    assert r.value("premium") == pytest.approx(0.20)
    assert r.value("unaffected_equity_value") == pytest.approx(5_000)
    assert r.value("premium_paid") == pytest.approx(1_000)


def test_transaction_multiples(r):
    assert r.value("ev_revenue") == pytest.approx(2.72)
    assert r.value("ev_ebitda") == pytest.approx(13.60)
    assert r.value("ev_ebit") == pytest.approx(17.00)
    assert r.value("pe") == pytest.approx(20.00)


def test_trading_multiples(r):
    assert r.value("unaffected_ev") == pytest.approx(5_800)
    assert r.value("unaffected_ev_ebitda") == pytest.approx(11.60)


def test_ebitda_margin(r):
    assert r.value("ebitda_margin") == pytest.approx(0.20)


def test_synergies(r):
    assert r.value("revenue_synergy_ebitda") == pytest.approx(30)
    assert r.value("total_synergy_ebitda") == pytest.approx(80)
    assert r.value("pro_forma_ebitda") == pytest.approx(580)
    assert r.value("synergy_adj_ev_ebitda") == pytest.approx(6_800 / 580)   # 11.72x
    assert round(r.value("synergy_adj_ev_ebitda"), 2) == 11.72
    assert r.value("after_tax_synergies") == pytest.approx(60)


def test_financing_split(r):
    assert r.value("financed_cash") == pytest.approx(2_400)
    assert r.value("financed_debt") == pytest.approx(2_400)
    assert r.value("financed_stock") == pytest.approx(1_200)


def test_clean_deal_has_no_warnings(r):
    assert r.warnings == []


# ------------------------------------------------------ facts vs assumptions --

def test_metrics_record_whether_they_use_assumptions(r):
    fact_only = ["equity_value", "enterprise_value", "premium", "ev_ebitda", "ebitda_margin"]
    assumption_based = ["pro_forma_ebitda", "synergy_adj_ev_ebitda", "financed_debt"]
    assert not any(r.metrics[k].depends_on_assumptions for k in fact_only)
    assert all(r.metrics[k].depends_on_assumptions for k in assumption_based)


def test_provenance_tags():
    tags = DEAL.provenance()
    assert tags["revenue"] == "fact"
    assert tags["offer_price_per_share"] == "fact"
    assert tags["cost_synergies"] == "assumption"
    assert tags["revenue_synergy_incremental_margin"] == "assumption"


# ------------------------------------------------------------- edge cases --

def test_margin_fallback_uses_target_margin_and_is_labelled():
    r = analyse_transaction(deal_with(assumptions={"revenue_synergy_incremental_margin": None}))
    assert r.value("revenue_synergy_ebitda") == pytest.approx(100 * 0.20)   # target margin 20%
    assert "ASSUMPTION" in r.metrics["revenue_synergy_ebitda"].note
    assert any("ASSUMING the target EBITDA margin" in w for w in r.warnings)


def test_negative_earnings_give_nm():
    r = analyse_transaction(deal_with(facts={"ebitda": -50, "ebit": -120, "net_income": -200}))
    for key in ("ev_ebitda", "ev_ebit", "pe", "unaffected_ev_ebitda"):
        assert r.value(key) is None
        assert r.metrics[key].note
    assert r.value("ebitda_margin") == pytest.approx(-0.02)  # a negative margin IS meaningful


def test_missing_optional_facts_give_unavailable_metrics():
    r = analyse_transaction(deal_with(facts={"net_income": None, "ebit": None}))
    assert r.value("pe") is None and "not provided" in r.metrics["pe"].note
    assert r.value("ev_ebit") is None


def test_net_cash_target_has_ev_below_equity_value():
    r = analyse_transaction(deal_with(facts={"total_debt": 0, "cash": 900}))
    assert r.value("enterprise_value") == pytest.approx(5_100)


def test_sample_json_matches_hand_calculated_case():
    r = analyse_transaction(load_deal(SAMPLE))
    assert r.value("enterprise_value") == pytest.approx(6_800)
    assert r.value("synergy_adj_ev_ebitda") == pytest.approx(6_800 / 580)
    assert r.warnings == []


def test_after_tax_synergy_metric_is_labelled_illustrative(r):
    m = r.metrics["after_tax_synergies"]
    assert m.label == "Illustrative after-tax synergy contribution"
    assert m.value == pytest.approx(60)                      # 80 × (1 − 25%), formula unchanged
    assert "not synergy cash flow, synergy NPV" in m.note
