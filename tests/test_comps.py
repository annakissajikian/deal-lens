"""
Step 5 tests: comparable companies, precedent transactions, football field.

Hand calculation (illustrative deal facts: EBITDA 500, net debt 800, 100m shares, offer $60, EV 6,800)
-----------------------------------------------------------------------------------------------------
Peers (EV / EBITDA): 10x, 12x, 14x, 16x, 18x
  min 10x · median 14x · mean 14x · max 18x
  Interquartile range (inclusive): 25th pct = 12x, 75th pct = 16x
  Implied EV     = 12 × 500 = 6,000   to  16 × 500 = 8,000
  Per share      = (6,000 − 800) / 100 = $52.00  to  (8,000 − 800) / 100 = $72.00
  Offer multiple = 6,800 / 500 = 13.60x
Selected range 11x–13x overrides the peers: EV 5,500–6,500 -> $47.00–$57.00
Even number of peers 10x, 12x, 14x, 16x: 25th pct = 10 + 0.75 × 2 = 11.5x; 75th pct = 14 + 0.25 × 2 = 14.5x

DCF bar = lowest and highest cells of the test_dcf.py grid (FCF 400/440/484, net debt 800, 100m shares):
  WACC 11%, g 1.5%: Σ PV 1,071.3709; TV 484 × 1.015 / 0.095 = 5,171.1579 -> PV 3,781.1061
                    EV 4,852.4769 -> (4,852.4769 − 800) / 100 = $40.52
  WACC 9%, g 2.5%:  Σ PV 1,111.0485; TV 484 × 1.025 / 0.065 = 7,632.3077 -> PV 5,893.5419
                    EV 7,004.5904 -> (7,004.5904 − 800) / 100 = $62.05
"""

from dataclasses import replace

import pytest

from finance.comps import analyse_valuation, implied_per_share, interquartile_range
from finance.dcf import analyse_dcf
from finance.models import DealInputError, MultipleValuation, Peer, ReferenceRange, ValuationInputs
from finance.validation import validate
from tests.test_dcf import DCF
from tests.test_transaction import DEAL
from tests.test_validation import sample_dict, write
from utils.io import load_deal

PEERS = tuple(Peer(n, m) for n, m in (("A", 10.0), ("B", 12.0), ("C", 14.0), ("D", 16.0), ("E", 18.0)))
COMPS = MultipleValuation("Trading comps (LTM EBITDA)", "comps", "LTM EBITDA", 500.0, PEERS)
PRECEDENTS = MultipleValuation("Precedents (LTM EBITDA)", "precedents", "LTM EBITDA", 500.0,
                               multiple_low=11.0, multiple_high=13.0)
WEEK52 = ReferenceRange("52-week range", 45.0, 62.0)


def deal_with_valuation(*multiples, references=(), dcf=None):
    return replace(DEAL, valuation=ValuationInputs(tuple(multiples), tuple(references)), dcf=dcf)


# --------------------------------------------------------- single formulas --

def test_interquartile_range():
    assert interquartile_range([10, 12, 14, 16, 18]) == (12, 16)
    assert interquartile_range([10, 12, 14, 16]) == (11.5, 14.5)
    assert interquartile_range([15]) == (15, 15)


def test_implied_per_share():
    assert implied_per_share(6_000, 800, 100) == pytest.approx(52.0)


# ---------------------------------------------------------- full analysis --

def test_comps_from_peers():
    r = analyse_valuation(deal_with_valuation(COMPS)).multiples[0]
    assert (r.peer_min, r.peer_median, r.peer_mean, r.peer_max) == (10, 14, 14, 18)
    assert (r.multiple_low, r.multiple_high, r.range_basis) == (12, 16, "interquartile range of peers")
    assert (r.ev_low, r.ev_high) == (6_000, 8_000)
    assert (r.per_share_low, r.per_share_high) == pytest.approx((52.0, 72.0))
    assert r.offer_multiple == pytest.approx(13.60)


def test_selected_range_overrides_peers():
    r = analyse_valuation(deal_with_valuation(replace(COMPS, multiple_low=11.0, multiple_high=13.0))).multiples[0]
    assert r.range_basis == "selected"
    assert (r.per_share_low, r.per_share_high) == pytest.approx((47.0, 57.0))
    assert r.peer_median == 14                                   # peer statistics still shown


def test_football_field_bars_in_order():
    deal = deal_with_valuation(COMPS, PRECEDENTS, references=[WEEK52], dcf=DCF)
    v = analyse_valuation(deal, analyse_dcf(deal))
    assert [(b.category, round(b.low, 2), round(b.high, 2)) for b in v.bars] == [
        ("DCF", 40.52, 62.05),                                   # corners of the DCF grid (see header)
        ("Trading comps", 52.0, 72.0), ("Precedent transactions", 47.0, 57.0),
        ("Market reference", 45.0, 62.0)]
    assert (v.offer_price, v.unaffected_price) == (60, 50)


def test_dcf_only_and_nothing():
    deal = replace(DEAL, dcf=DCF)
    assert [b.category for b in analyse_valuation(deal, analyse_dcf(deal)).bars] == ["DCF"]
    assert analyse_valuation(DEAL) is None


# ------------------------------------------------------------------ errors --

@pytest.mark.parametrize("multiple, expected", [
    (replace(COMPS, metric_value=0.0), "metric_value must be a number greater than zero"),
    (replace(COMPS, method="lbo"), "method must be 'comps' or 'precedents'"),
    (replace(COMPS, name=" "), "name must be non-empty text"),
    (replace(COMPS, peers=()), "needs peers or a selected multiple range"),
    (replace(COMPS, peers=(Peer("A", -2.0),)), "peers[0] needs a name and a multiple greater than zero"),
    (replace(PRECEDENTS, multiple_low=15.0), "multiple_low (15.0) must not exceed multiple_high (13.0)"),
    (replace(PRECEDENTS, multiple_high=None, peers=PEERS), "must both be numbers greater than zero"),
])
def test_rejects_bad_multiples(multiple, expected):
    with pytest.raises(DealInputError) as exc:
        validate(deal_with_valuation(multiple))
    assert any(expected in e for e in exc.value.errors)


def test_rejects_bad_reference_range():
    with pytest.raises(DealInputError) as exc:
        validate(deal_with_valuation(references=[ReferenceRange("x", 70.0, 60.0)]))
    assert any("low (70.0) must not exceed high (60.0)" in e for e in exc.value.errors)


# ------------------------------------------------------------- JSON loading --

def test_loader_reads_valuation(tmp_path):
    data = sample_dict()
    data["valuation"] = {
        "multiples": [{"name": "Trading comps (LTM EBITDA)", "method": "comps", "metric_label": "LTM EBITDA",
                       "metric_value": 500.0, "peers": [{"name": n, "multiple": m} for n, m in
                                                        (("A", 10.0), ("B", 12.0), ("C", 14.0), ("D", 16.0),
                                                         ("E", 18.0))]}],
        "references": [{"name": "52-week range", "low": 45.0, "high": 62.0}]}
    assert load_deal(write(tmp_path, data)).valuation == ValuationInputs((COMPS,), (WEEK52,))


@pytest.mark.parametrize("bad, expected", [
    ([], "Section 'valuation' must be an object"),
    ({"multiples": {}}, "valuation.multiples must be a list"),
    ({"multiples": [5]}, r"valuation.multiples\[0\] must be an object"),
    ({"multiple": []}, "Unknown field in 'valuation': 'multiple'"),
    ({"references": [{"name": "x", "low": 1, "hi": 2}]}, r"Unknown field in 'valuation.references\[0\]'"),
])
def test_loader_rejects_malformed_valuation(tmp_path, bad, expected):
    data = sample_dict()
    data["valuation"] = bad
    with pytest.raises(DealInputError, match=expected):
        load_deal(write(tmp_path, data))
