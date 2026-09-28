"""
Validation tests: bad inputs must be rejected (ERROR) and odd inputs flagged (WARNING).
"""

import json
from datetime import date

import pytest

from finance.models import DealInputError
from finance.transaction import analyse_transaction
from finance.validation import validate
from tests.test_transaction import DEAL, deal_with
from utils.io import load_deal


def errors_for(**changes) -> list[str]:
    facts = {k: v for k, v in changes.items() if hasattr(DEAL.facts, k)}
    assumptions = {k: v for k, v in changes.items() if hasattr(DEAL.assumptions, k)}
    with pytest.raises(DealInputError) as exc:
        validate(deal_with(facts, assumptions))
    return exc.value.errors


# ------------------------------------------------------------------ ERRORS --

@pytest.mark.parametrize("field, value", [
    ("diluted_shares_outstanding", 0),
    ("diluted_shares_outstanding", -100),
    ("offer_price_per_share", -60),
    ("offer_price_per_share", 0),
    ("unaffected_share_price", 0),
])
def test_rejects_non_positive_prices_and_shares(field, value):
    assert any(field in e for e in errors_for(**{field: value}))


@pytest.mark.parametrize("field", ["revenue", "total_debt", "cash", "cost_synergies", "revenue_synergies"])
def test_rejects_negative_amounts(field):
    assert any(field in e for e in errors_for(**{field: -1}))


@pytest.mark.parametrize("field, value", [
    ("tax_rate", 25),                                # 25 instead of 0.25
    ("tax_rate", -0.1),
    ("revenue_synergy_incremental_margin", 1.5),
    ("financing_debt", -0.2),
])
def test_rejects_impossible_percentages(field, value):
    assert any(field in e for e in errors_for(**{field: value}))


def test_rejects_financing_mix_not_totalling_100():
    errs = errors_for(financing_cash=0.5, financing_debt=0.3, financing_stock=0.0)
    assert any("Financing mix must total 100%" in e for e in errs)


def test_accepts_financing_mix_within_rounding():
    validate(deal_with(assumptions={"financing_cash": 0.3333, "financing_debt": 0.3333,
                                    "financing_stock": 0.3334}))


def test_rejects_text_instead_of_number():
    assert any("revenue must be a finite number" in e for e in errors_for(revenue="2,500"))


def test_reports_all_errors_at_once():
    errs = errors_for(diluted_shares_outstanding=0, tax_rate=25, financing_cash=0.8)
    assert len(errs) == 3


def test_rejects_empty_names():
    from dataclasses import replace
    from finance.models import DealInputs
    bad = DealInputs(replace(DEAL.info, target="  "), DEAL.facts, DEAL.assumptions)
    with pytest.raises(DealInputError, match="target must be non-empty text"):
        validate(bad)


# ---------------------------------------------------------------- WARNINGS --

def test_warns_on_stated_equity_value_mismatch():
    r = analyse_transaction(deal_with(facts={"stated_equity_value": 6_500}))   # +8.3%
    assert any("Stated equity value" in w for w in r.warnings)
    assert r.value("equity_value") == pytest.approx(6_000)   # calculated figure still used


def test_no_warning_when_stated_equity_value_within_tolerance():
    r = analyse_transaction(deal_with(facts={"stated_equity_value": 6_050}))   # +0.8%
    assert not any("Stated equity value" in w for w in r.warnings)


def test_warns_when_premium_exceeds_review_threshold():
    r = analyse_transaction(deal_with(facts={"offer_price_per_share": 80}))    # 60%
    assert any("exceeds the configured 50% review threshold" in w for w in r.warnings)
    assert not any("unusually" in w for w in r.warnings)


def test_warns_on_negative_premium():
    r = analyse_transaction(deal_with(facts={"offer_price_per_share": 45}))
    assert r.value("premium") == pytest.approx(-0.10)
    assert any("negative premium" in w for w in r.warnings)


def test_warns_on_missing_optional_fields():
    r = analyse_transaction(deal_with(facts={"net_income": None, "stated_equity_value": None},
                                      assumptions={"tax_rate": None}))
    joined = " ".join(r.warnings)
    assert "net_income" in joined and "stated_equity_value" in joined and "tax_rate" in joined


# ------------------------------------------------------------- JSON loading --

def write(tmp_path, data) -> str:
    p = tmp_path / "deal.json"
    p.write_text(json.dumps(data))
    return str(p)


def sample_dict() -> dict:
    return {"deal": {"acquirer": "A", "target": "B", "sector": "X"},
            "facts": {"offer_price_per_share": 60, "unaffected_share_price": 50,
                      "diluted_shares_outstanding": 100, "revenue": 2500, "ebitda": 500,
                      "total_debt": 1200, "cash": 400},
            "assumptions": {}}


def test_loader_rejects_unknown_field(tmp_path):
    data = sample_dict()
    data["facts"]["ebidta"] = 500
    with pytest.raises(DealInputError, match="ebidta"):
        load_deal(write(tmp_path, data))


def test_loader_rejects_missing_section(tmp_path):
    data = sample_dict()
    del data["assumptions"]
    with pytest.raises(DealInputError, match="assumptions"):
        load_deal(write(tmp_path, data))


def test_loader_rejects_missing_required_fact(tmp_path):
    data = sample_dict()
    del data["facts"]["revenue"]
    with pytest.raises(DealInputError, match="revenue"):
        load_deal(write(tmp_path, data))


def test_loader_rejects_bad_date(tmp_path):
    data = sample_dict()
    data["deal"]["announcement_date"] = "15/01/2026"
    with pytest.raises(DealInputError, match="YYYY-MM-DD"):
        load_deal(write(tmp_path, data))


# ================================================== Step 1 hardening tests ==

REQUIRED_NUMERIC_FIELDS = [
    "offer_price_per_share", "unaffected_share_price", "diluted_shares_outstanding",
    "revenue", "ebitda", "total_debt", "cash",
    "cost_synergies", "revenue_synergies",
    "financing_cash", "financing_debt", "financing_stock",
]
OPTIONAL_NUMERIC_FIELDS = [
    "net_income", "ebit", "stated_equity_value", "revenue_synergy_incremental_margin", "tax_rate",
]


# ---- 1. None / null ---------------------------------------------------------

@pytest.mark.parametrize("field", REQUIRED_NUMERIC_FIELDS)
def test_rejects_none_for_every_required_numeric_field(field):
    errs = errors_for(**{field: None})
    assert any(f"{field} is required" in e for e in errs)


@pytest.mark.parametrize("field", OPTIONAL_NUMERIC_FIELDS)
def test_accepts_none_for_optional_numeric_fields(field):
    analyse_transaction(deal_with(**({"facts": {field: None}} if hasattr(DEAL.facts, field)
                                     else {"assumptions": {field: None}})))


def test_json_null_for_required_field_raises_deal_input_error(tmp_path):
    data = sample_dict()
    data["facts"]["revenue"] = None
    with pytest.raises(DealInputError, match="revenue is required"):
        analyse_transaction(load_deal(write(tmp_path, data)))


# ---- 2. NaN and infinity ------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("field", ["revenue", "offer_price_per_share", "cost_synergies", "tax_rate"])
def test_rejects_non_finite_numbers(field, bad):
    assert any(f"{field} must be a finite number" in e for e in errors_for(**{field: bad}))


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_rejects_non_finite_numbers_from_json(tmp_path, literal):
    p = tmp_path / "deal.json"
    p.write_text(json.dumps(sample_dict()).replace('"ebitda": 500', f'"ebitda": {literal}'))
    with pytest.raises(DealInputError, match="ebitda must be a finite number"):
        analyse_transaction(load_deal(p))


def test_rejects_boolean_as_number():
    assert any("revenue must be a finite number" in e for e in errors_for(revenue=True))


# ---- 3. JSON structure --------------------------------------------------------

def test_loader_rejects_non_object_root(tmp_path):
    with pytest.raises(DealInputError, match="JSON root must be an object"):
        load_deal(write(tmp_path, [sample_dict()]))


@pytest.mark.parametrize("section, bad_value", [
    ("deal", []), ("deal", "Northwind"), ("facts", []), ("facts", 5),
    ("assumptions", None), ("assumptions", ["cost_synergies", 50]),
])
def test_loader_rejects_malformed_section_types(tmp_path, section, bad_value):
    data = sample_dict()
    data[section] = bad_value
    with pytest.raises(DealInputError, match=f"Section '{section}' must be an object"):
        load_deal(write(tmp_path, data))


# ---- 4. Announcement date -----------------------------------------------------

def test_loader_accepts_valid_date(tmp_path):
    data = sample_dict()
    data["deal"]["announcement_date"] = "2026-01-15"
    assert load_deal(write(tmp_path, data)).info.announcement_date == date(2026, 1, 15)


def test_loader_accepts_null_date(tmp_path):
    data = sample_dict()
    data["deal"]["announcement_date"] = None
    assert load_deal(write(tmp_path, data)).info.announcement_date is None


@pytest.mark.parametrize("bad", ["15/01/2026", 123, "2026-02-30", "", "20260115", ["2026-01-15"]])
def test_loader_rejects_invalid_dates(tmp_path, bad):
    data = sample_dict()
    data["deal"]["announcement_date"] = bad
    with pytest.raises(DealInputError, match="YYYY-MM-DD"):
        load_deal(write(tmp_path, data))


def test_validate_rejects_non_date_object():
    from dataclasses import replace
    from finance.models import DealInputs
    bad = DealInputs(replace(DEAL.info, announcement_date="2026-01-15"), DEAL.facts, DEAL.assumptions)
    with pytest.raises(DealInputError, match="YYYY-MM-DD"):
        validate(bad)


# ================================================== Step 3: loader helpers ==

from utils.io import list_sample_deals, load_sources


def test_list_sample_deals_labels_every_file():
    deals = list_sample_deals()
    assert deals["Northwind Holdings / Apex Components"].name == "illustrative_deal.json"
    assert deals["Microsoft Corporation / Activision Blizzard, Inc."].name == "microsoft_activision.json"


def test_list_sample_deals_keeps_invalid_files_under_their_name(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "ok.json").write_text(json.dumps(sample_dict()))
    assert list(list_sample_deals(tmp_path)) == ["broken", "A / B"]


def test_load_sources_returns_provenance_blocks(tmp_path):
    data = sample_dict()
    data["_sources"] = {"revenue": {"page": "F-4"}}
    data["_documents"] = {"10K": "annual report"}
    assert load_sources(write(tmp_path, data)) == {
        "documents": {"10K": "annual report"}, "sources": {"revenue": {"page": "F-4"}}, "cross_checks": {}}


def test_load_sources_empty_when_file_has_none(tmp_path):
    assert load_sources(write(tmp_path, sample_dict())) == {"documents": {}, "sources": {}, "cross_checks": {}}


def test_md_escapes_dollar_signs():
    from utils.formatting import md
    assert md("$ 3,650 and $ 3,608") == r"\$ 3,650 and \$ 3,608"
    assert md("no dollars") == "no dollars"
