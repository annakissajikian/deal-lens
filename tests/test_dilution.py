"""
Step 2 tests: fully diluted shares with the treasury stock method (TSM).

Hand calculation for the share build used below (offer price $60)
-----------------------------------------------------------------
Basic shares                                            = 100
Tranche A: 6 options @ $30  -> in the money, proceeds 6 × 30 = 180
Tranche B: 4 options @ $45  -> in the money, proceeds 4 × 45 = 180
Tranche C: 5 options @ $75  -> out of the money (75 ≥ 60), ignored
Options exercised     = 6 + 4                           = 10
Shares repurchased    = (180 + 180) / 60                = 6
Net new option shares = 10 − 6                          = 4
RSUs / PSUs                                             = 2
Fully diluted shares  = 100 + 4 + 2                     = 106

Deal with the illustrative facts but this share build:
Equity value      = 60 × 106             = 6,360
Enterprise value  = 6,360 + 1,200 − 400  = 7,160
Unaffected equity = 50 × 106             = 5,300   -> premium paid 1,060
Premium           = 60 / 50 − 1          = 20%     (unchanged: per-share figure)
EV / EBITDA       = 7,160 / 500          = 14.32x
"""

import json

import pytest

from finance.dilution import diluted_share_count, fully_diluted_shares, treasury_stock_method
from finance.models import DealInputError, OptionTranche, ShareBuild
from finance.transaction import analyse_transaction
from finance.validation import validate
from tests.test_transaction import DEAL, FACTS, deal_with
from tests.test_validation import sample_dict, write
from utils.io import load_deal

TRANCHES = (OptionTranche(6, 30), OptionTranche(4, 45), OptionTranche(5, 75))
BUILD = ShareBuild(basic_shares=100, option_tranches=TRANCHES, rsus=2, as_of="2026-01-10")


def build_with(**changes) -> ShareBuild:
    from dataclasses import replace
    return replace(BUILD, **changes)


def tsm_deal(build=BUILD, **facts):
    """Illustrative deal whose share count comes from a share build instead of being entered."""
    return deal_with(facts={"diluted_shares_outstanding": None, "share_build": build, **facts})


# --------------------------------------------------------- single formulas --

def test_single_tranche_from_the_plan():
    # 10 options @ $40, price $60: exercised 10, repurchased 10 × 40 / 60 = 6.667, net 3.333
    exercised, repurchased = treasury_stock_method((OptionTranche(10, 40),), 60)
    assert exercised == 10
    assert repurchased == pytest.approx(6.6667, abs=1e-4)
    assert exercised - repurchased == pytest.approx(3.3333, abs=1e-4)


def test_tsm_over_several_tranches():
    exercised, repurchased = treasury_stock_method(TRANCHES, 60)
    assert exercised == 10                        # tranche C excluded
    assert repurchased == pytest.approx(6)        # 360 / 60


def test_fully_diluted_shares():
    assert fully_diluted_shares(BUILD, 60) == pytest.approx(106)


def test_at_the_money_options_add_nothing():
    # strike = price: exercise proceeds buy back exactly the new shares -> excluded, net 0
    assert treasury_stock_method((OptionTranche(10, 60),), 60) == (0, 0)


def test_all_out_of_the_money():
    # only tranche C at a $60 offer: nothing exercised -> 100 + 0 + 2 = 102
    assert fully_diluted_shares(build_with(option_tranches=(OptionTranche(5, 75),)), 60) == pytest.approx(102)


def test_no_options_no_rsus_equals_basic():
    assert fully_diluted_shares(ShareBuild(basic_shares=100), 60) == 100


def test_higher_price_brings_more_options_into_the_money():
    # at $80, tranche C is in the money too:
    # exercised 15; proceeds 180 + 180 + 375 = 735; repurchased 735 / 80 = 9.1875
    # fully diluted = 100 + 15 − 9.1875 + 2 = 107.8125
    assert fully_diluted_shares(BUILD, 80) == pytest.approx(107.8125)


def test_tranches_matter_versus_one_weighted_average_strike():
    # Aggregating all 15 options at the weighted-average strike 735 / 15 = $49 (< $60) would
    # exercise all 15 and repurchase 15 × 49 / 60 = 12.25 -> net 2.75, not the correct 4.
    aggregate = treasury_stock_method((OptionTranche(15, 49),), 60)
    by_tranche = treasury_stock_method(TRANCHES, 60)
    assert aggregate[0] - aggregate[1] == pytest.approx(2.75)
    assert by_tranche[0] - by_tranche[1] == pytest.approx(4)


def test_share_count_source():
    assert diluted_share_count(FACTS) == 100                       # entered directly
    assert diluted_share_count(tsm_deal().facts) == pytest.approx(106)  # share build


# ---------------------------------------------------------- full analysis --

def test_analysis_uses_share_build():
    r = analyse_transaction(tsm_deal())
    assert r.value("basic_shares") == 100
    assert r.value("options_exercised") == pytest.approx(10)
    assert r.value("shares_repurchased") == pytest.approx(6)
    assert r.value("net_option_shares") == pytest.approx(4)
    assert r.value("rsus") == 2
    assert r.value("fully_diluted_shares") == pytest.approx(106)
    assert r.value("equity_value") == pytest.approx(6_360)
    assert r.value("enterprise_value") == pytest.approx(7_160)
    assert r.value("unaffected_equity_value") == pytest.approx(5_300)
    assert r.value("premium_paid") == pytest.approx(1_060)
    assert r.value("premium") == pytest.approx(0.20)
    assert r.value("ev_ebitda") == pytest.approx(14.32)


def test_share_count_metrics_are_facts_with_notes():
    r = analyse_transaction(tsm_deal())
    share_metrics = [m for m in r.metrics.values() if m.section == "Share count"]
    assert len(share_metrics) == 6
    assert not any(m.depends_on_assumptions for m in share_metrics)
    assert "5.00m options" in r.metrics["options_exercised"].note     # tranche C flagged
    assert "unaffected" in r.metrics["fully_diluted_shares"].note     # limitation stated


def test_entered_share_count_shows_no_share_section():
    r = analyse_transaction(DEAL)
    assert not any(m.section == "Share count" for m in r.metrics.values())
    assert r.value("equity_value") == pytest.approx(6_000)          # Step 1 unchanged


# ---------------------------------------------------------------- warnings --

def test_stated_equity_value_cross_check_uses_share_build():
    # stated 6,000 vs 60 × 106 = 6,360 -> −5.7% gap -> warning
    r = analyse_transaction(tsm_deal())
    assert any("Stated equity value" in w for w in r.warnings)
    r = analyse_transaction(tsm_deal(stated_equity_value=6_360))
    assert not any("Stated equity value" in w for w in r.warnings)


def test_warns_when_entered_and_calculated_share_counts_differ():
    # entered 100 vs build 106 -> 100 / 106 − 1 = −5.7% (> 1%) -> warning, build is used
    r = analyse_transaction(tsm_deal(diluted_shares_outstanding=100))
    assert any("Entered diluted shares" in w for w in r.warnings)
    assert r.value("equity_value") == pytest.approx(6_360)
    # entered 106.5 -> +0.5% (within 1%) -> no warning
    r = analyse_transaction(tsm_deal(diluted_shares_outstanding=106.5))
    assert not any("Entered diluted shares" in w for w in r.warnings)


# ------------------------------------------------------------------ errors --

def test_requires_either_entered_shares_or_share_build():
    with pytest.raises(DealInputError, match="or provide a share_build"):
        validate(deal_with(facts={"diluted_shares_outstanding": None}))


@pytest.mark.parametrize("changes, expected", [
    ({"basic_shares": 0}, "basic_shares must be greater than zero"),
    ({"basic_shares": -100}, "basic_shares must be greater than zero"),
    ({"basic_shares": float("nan")}, "basic_shares must be a finite number"),
    ({"basic_shares": None}, "basic_shares must be a finite number"),
    ({"rsus": -1}, "rsus cannot be negative"),
    ({"option_tranches": (OptionTranche(-5, 30),)}, "option_tranches[0].number cannot be negative"),
    ({"option_tranches": (OptionTranche(5, -30),)}, "option_tranches[0].strike cannot be negative"),
    ({"option_tranches": (OptionTranche(5, "30"),)}, "option_tranches[0].strike must be a finite number"),
])
def test_rejects_bad_share_build(changes, expected):
    with pytest.raises(DealInputError) as exc:
        validate(tsm_deal(build_with(**changes)))
    assert any(expected in e for e in exc.value.errors)


def test_lists_all_share_build_errors_together():
    with pytest.raises(DealInputError) as exc:
        validate(tsm_deal(build_with(basic_shares=-1, rsus=-1), revenue=-5))
    joined = " ".join(exc.value.errors)
    assert "basic_shares" in joined and "rsus" in joined and "revenue" in joined


# ------------------------------------------------------------- JSON loading --

def share_build_dict() -> dict:
    data = sample_dict()
    del data["facts"]["diluted_shares_outstanding"]
    data["facts"]["share_build"] = {
        "_source": "comment keys are ignored",
        "basic_shares": 100, "rsus": 2, "as_of": "2026-01-10",
        "option_tranches": [{"number": 6, "strike": 30}, {"number": 4, "strike": 45},
                            {"number": 5, "strike": 75}],
    }
    return data


def test_loader_reads_share_build(tmp_path):
    deal = load_deal(write(tmp_path, share_build_dict()))
    assert deal.facts.share_build == BUILD
    assert analyse_transaction(deal).value("fully_diluted_shares") == pytest.approx(106)


@pytest.mark.parametrize("mutate, expected", [
    (lambda sb: sb.update(option_tranches={"number": 6}), "option_tranches must be a list"),
    (lambda sb: sb["option_tranches"].append(5), r"option_tranches\[3\] must be an object"),
    (lambda sb: sb["option_tranches"][0].update(strik=30), "Unknown field in 'option_tranches\\[0\\]'"),
    (lambda sb: sb["option_tranches"][1].pop("strike"), "strike"),
    (lambda sb: sb.update(basic=100), "Unknown field in 'share_build'"),
])
def test_loader_rejects_malformed_share_build(tmp_path, mutate, expected):
    data = share_build_dict()
    mutate(data["facts"]["share_build"])
    with pytest.raises(DealInputError, match=expected):
        load_deal(write(tmp_path, data))


def test_loader_rejects_share_build_that_is_not_an_object(tmp_path):
    data = share_build_dict()
    data["facts"]["share_build"] = [100, 2]
    with pytest.raises(DealInputError, match="share_build must be an object"):
        load_deal(write(tmp_path, data))
