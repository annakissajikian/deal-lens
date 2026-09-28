"""
Step 3b tests: the "New deal" input form.

Hand calculation for the form scenario (illustrative deal, offer changed to $66)
-------------------------------------------------------------------------------
Equity value = 66 × 100            = 6,600
EV           = 6,600 + 1,200 − 400 = 7,400
Premium      = 66 / 50 − 1         = 32.0%
EV / EBITDA  = 7,400 / 500         = 14.80x
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finance.transaction import analyse_transaction
from ui.deal_form import BLANK, SHARE_MODES, build_deal_dict, errors_by_group, form_values_from_dict
from utils.io import deal_filename, deal_from_dict, load_deal, save_deal

ROOT = Path(__file__).parent.parent
SAMPLES = [ROOT / "tests" / "fixtures" / "illustrative_deal.json",
           ROOT / "data" / "sample_deals" / "microsoft_activision.json"]
pytestmark = pytest.mark.usefixtures("isolated_deal_folders")
APP = str(ROOT / "app.py")
ILLUSTRATIVE = "Northwind Holdings / Apex Components"


def raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sections(d: dict) -> dict:
    return {k: d[k] for k in ("deal", "facts", "assumptions")}


# ------------------------------------------------ one validation path --

@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_deal_from_dict_equals_load_deal(path):
    assert deal_from_dict(raw(path)) == load_deal(path)


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_form_round_trip_reproduces_every_sample_deal(path):
    # JSON -> form values -> JSON gives back the same deal (percent conversion included)
    assert sections(build_deal_dict(form_values_from_dict(raw(path)))) == sections(raw(path))


# ------------------------------------------------------ build_deal_dict --

def test_blank_form_keeps_blanks_as_null_not_zero():
    d = build_deal_dict(BLANK)
    assert d["facts"]["revenue"] is None and d["facts"]["stated_equity_value"] is None
    assert d["facts"]["diluted_shares_outstanding"] is None
    assert d["assumptions"]["tax_rate"] is None
    assert d["assumptions"]["cost_synergies"] == 0.0                       # form default, not a blank
    assert d["assumptions"]["financing_cash"] == 1.0                       # 100% -> 1.0
    assert d["deal"]["announcement_date"] is None
    assert "not source-verified" in d["_comment"]


@pytest.mark.parametrize("typed, stored", [(25, 0.25), (33.33, 0.3333), (100, 1.0), (0, 0.0), (7, 0.07)])
def test_percentages_typed_as_whole_numbers(typed, stored):
    assert build_deal_dict(BLANK | {"tax_rate": typed})["assumptions"]["tax_rate"] == stored


def test_share_count_methods_are_exclusive():
    direct = build_deal_dict(BLANK | {"diluted_shares_outstanding": 100.0})["facts"]
    assert direct["diluted_shares_outstanding"] == 100.0 and "share_build" not in direct
    built = build_deal_dict(BLANK | {"share_mode": SHARE_MODES[1], "basic_shares": 100.0,
                                     "diluted_shares_outstanding": 999.0})["facts"]
    assert built["share_build"]["basic_shares"] == 100.0 and "diluted_shares_outstanding" not in built


def test_tranche_rows_empty_dropped_half_filled_kept():
    rows = [{"number": 6.0, "strike": 30.0}, {"number": None, "strike": None}, {"number": 4.0, "strike": None}]
    build = build_deal_dict(BLANK | {"share_mode": SHARE_MODES[1], "basic_shares": 100.0,
                                     "option_tranches": rows})["facts"]["share_build"]
    assert build["option_tranches"] == [{"number": 6.0, "strike": 30.0}, {"number": 4.0, "strike": None}]


def test_half_filled_tranche_is_a_validation_error():
    values = form_values_from_dict(raw(SAMPLES[0])) | {
        "share_mode": SHARE_MODES[1], "basic_shares": 100.0, "option_tranches": [{"number": 4.0, "strike": None}]}
    with pytest.raises(Exception, match=r"option_tranches\[0\]\.strike must be a finite number"):
        analyse_transaction(deal_from_dict(build_deal_dict(values)))


def test_blank_rsus_mean_none():
    # basic 100, 10 options @ $40, offer $60 -> 100 + 10 − 400/60 = 103.3333; blank RSUs add nothing
    values = form_values_from_dict(raw(SAMPLES[0])) | {
        "share_mode": SHARE_MODES[1], "basic_shares": 100.0, "rsus": None,
        "option_tranches": [{"number": 10.0, "strike": 40.0}]}
    r = analyse_transaction(deal_from_dict(build_deal_dict(values)))
    assert r.value("fully_diluted_shares") == pytest.approx(103.3333, abs=1e-4)


# --------------------------------------------------------- errors_by_group --

def test_errors_are_placed_under_the_right_group():
    placed = errors_by_group([
        "revenue_synergies cannot be negative.",
        "revenue is required and cannot be null/None.",
        "ebit must be a finite number or null (got 'x').",
        "Financing mix must total 100% (currently 90.0%).",
        "share_build.basic_shares must be greater than zero.",
        "Something unexpected.",
    ])
    assert placed["Assumptions"] == ["revenue_synergies cannot be negative.",
                                     "Financing mix must total 100% (currently 90.0%)."]
    assert placed["Target financials"] == ["revenue is required and cannot be null/None.",
                                           "ebit must be a finite number or null (got 'x')."]
    assert placed["Share count"] == ["share_build.basic_shares must be greater than zero."]
    assert not any("unexpected" in e for group in placed.values() for e in group)   # summary only


# ----------------------------------------------------------------- saving --

def test_deal_filename_is_safe():
    assert deal_filename({"deal": {"acquirer": "Microsoft Corp.", "target": "Activision Blizzard, Inc."}}) \
        == "microsoft_corp_activision_blizzard_inc.json"
    assert deal_filename({"deal": {"acquirer": "../../etc", "target": ""}}) == "etc.json"
    assert deal_filename({}) == "deal.json"


def test_save_refuses_to_overwrite_unless_asked(tmp_path):
    d = raw(SAMPLES[0])
    path = save_deal(d, tmp_path / "user_deals")                 # folder created
    assert path.name == "northwind_holdings_apex_components.json"
    with pytest.raises(FileExistsError):
        save_deal(d, tmp_path / "user_deals")
    save_deal(d, tmp_path / "user_deals", overwrite=True)


def test_saved_file_reloads_to_the_same_analysis(tmp_path):
    d = build_deal_dict(form_values_from_dict(raw(SAMPLES[0])))
    reloaded = analyse_transaction(load_deal(save_deal(d, tmp_path)))
    direct = analyse_transaction(deal_from_dict(d))
    assert {k: m.value for k, m in reloaded.metrics.items()} == {k: m.value for k, m in direct.metrics.items()}


# ---------------------------------------------------------- app, headless --

def new_deal_app(start_from: str | None = ILLUSTRATIVE) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio(key="mode").set_value("Enter a new deal").run()
    if start_from:
        at.selectbox(key="f_start").select(start_from).run()
    assert not at.exception, at.exception
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label.startswith(label)).click().run()
    assert not at.exception, at.exception
    return at


def test_form_runs_the_hand_calculated_scenario():
    at = new_deal_app()
    at.number_input(key="f_offer_price_per_share").set_value(66.0).run()
    click(at, "Run analysis")
    assert {m.label: m.value for m in at.metric} == {
        "Transaction enterprise value": "$7,400m", "Transaction equity value": "$6,600m",
        "Acquisition premium": "32.0%", "EV / EBITDA": "14.80x"}
    assert len(at.get("download_button")) == 1


def test_invalid_input_shows_errors_inline_and_no_results():
    at = new_deal_app()
    at.number_input(key="f_tax_rate").set_value(250.0).run()
    click(at, "Run analysis")
    errors = [e.value for e in at.error]
    assert any(e.startswith("The deal cannot be analysed (1 problem(s))") for e in errors)   # summary
    assert any(e.startswith("tax_rate must be a decimal between 0 and 1") for e in errors)   # inline
    assert not at.metric and not at.get("download_button")


def test_blank_required_field_is_reported():
    at = new_deal_app()
    at.number_input(key="f_revenue").set_value(None).run()
    click(at, "Run analysis")
    assert any(e.value.startswith("revenue is required") for e in at.error)


def test_results_hidden_when_inputs_change_after_a_run():
    at = new_deal_app()
    click(at, "Run analysis")
    assert at.metric
    at.number_input(key="f_offer_price_per_share").set_value(70.0).run()
    assert not at.metric
    assert any(i.value.startswith("Inputs have changed") for i in at.info)


def test_values_survive_switching_modes():
    at = new_deal_app()
    at.number_input(key="f_offer_price_per_share").set_value(66.0).run()
    at.sidebar.radio(key="mode").set_value("Analyse a saved deal").run()
    at.sidebar.radio(key="mode").set_value("Enter a new deal").run()
    assert at.number_input(key="f_offer_price_per_share").value == 66.0


def test_save_button_writes_and_protects_existing_file(isolated_deal_folders):
    at = new_deal_app()
    click(at, "Run analysis")
    click(at, "Save to data/user_deals/")
    assert (isolated_deal_folders / "northwind_holdings_apex_components.json").exists()
    assert any(s.value.startswith("Saved to data/user_deals/") for s in at.success)
    click(at, "Save to data/user_deals/")
    assert any("already exists" in e.value for e in at.error)
    at.checkbox(key="f_overwrite").check().run()
    click(at, "Save to data/user_deals/")
    assert any(s.value.startswith("Saved to data/user_deals/") for s in at.success)
