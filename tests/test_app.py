"""
Step 3 tests: the Streamlit app, run headless with Streamlit's AppTest.

These check that the app shows the engine's numbers (the locked Step 1 and
Step 2b outputs), keeps the provenance tags, and always shows the disclaimer.
They do not re-test the finance: that is done in the other test files.
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finance.transaction import analyse_transaction
from ui.overview import intentionally_empty
from utils.io import load_deal, load_sources

APP = str(Path(__file__).parent.parent / "app.py")
pytestmark = pytest.mark.usefixtures("isolated_deal_folders")   # the illustrative fixture + Activision
ACTIVISION_FILE = Path(__file__).parent.parent / "data" / "sample_deals" / "microsoft_activision.json"
ILLUSTRATIVE = "Example: Northwind Holdings / Apex Components"
ACTIVISION = "Example: Microsoft Corporation / Activision Blizzard, Inc."
DISCLAIMER = "Preliminary analytical tool for educational purposes. Not investment advice."


def run_app(deal: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio(key="mode").set_value("Example & saved deals").run()
    at.sidebar.selectbox[0].select(deal).run()
    assert not at.exception, at.exception
    return at


def tiles(at: AppTest, tab: int = 0) -> dict[str, str]:
    """Metric tiles on one tab (0 = Deal Overview, 2 = DCF)."""
    return {m.label: m.value for m in at.main.tabs[tab].metric}


def table_with(at: AppTest, column: str, value: str):
    """First table on the page (interactive or static) whose `column` contains `value`."""
    for df in [d.value for d in at.dataframe] + [t.value for t in at.table]:
        if column in df.columns and value in df[column].values:
            return df
    raise AssertionError(f"no table with {column} = {value!r}")


def test_dropdown_lists_both_sample_deals():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio(key="mode").set_value("Example & saved deals").run()
    assert at.sidebar.selectbox[0].options == [ILLUSTRATIVE, ACTIVISION]


def landing(at: AppTest) -> str:
    return at.get("html")[0].proto.body


def test_app_opens_on_the_landing_page():
    at = AppTest.from_file(APP, default_timeout=30).run()
    page = landing(at)
    assert '<h1 class="dl-headline">deals.</h1>' in page
    assert 'href="?go=new" target="_self" class="dl-primary">Analyse a deal</a>' in page
    assert 'href="?go=example" target="_self" class="dl-ghost">Try an example' in page
    assert not at.sidebar.selectbox                                   # no deal shown by default


def test_landing_stats_come_from_the_engine():
    page = landing(AppTest.from_file(APP, default_timeout=30).run())
    for value, label in (("20.39x", "EV / EBITDA"), ("45.3%", "Premium"), ("$68,824m", "Enterprise value")):
        assert f'<div class="dl-stat-value">{value}</div><div class="dl-stat-label">{label}</div>' in page
    assert "Microsoft Corporation / Activision Blizzard, Inc. · calculated by DealLens" in page
    for invented in ("10.4", "23.6%", "$747m"):                      # the mock-up's placeholder figures
        assert invented not in page


def test_landing_css_is_scoped():
    page = landing(AppTest.from_file(APP, default_timeout=30).run())
    page_css, landing_css = page.split("</style>")[:2]
    # the landing's own CSS only styles .dl-* elements (never html / body / :root)
    selectors = [line.split("{")[0].strip() for line in landing_css.splitlines()
                 if "{" in line and not line.startswith(" ")]
    assert all(sel.startswith((".dl-", "@")) for sel in selectors), selectors
    # the Home-only page CSS just hides the sidebar / header and removes the padding
    assert '[data-testid="stSidebar"]' in page_css and '[data-testid="stHeader"]' in page_css
    assert "display: none !important" in page_css and "padding: 0 !important" in page_css


def test_home_is_full_screen_without_nav_or_footer():
    at = AppTest.from_file(APP, default_timeout=30).run()
    page = landing(at)
    assert "height: 100vh" in page and "border-radius: 20px" not in page
    assert "Open app" not in page and "dl-logo" not in page           # removed from the top of the page
    assert not at.main.caption and not at.main.divider                # no footer on the full-screen Home


def test_page_css_only_on_home():
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["go"] = "example"
    at.run()
    assert not [h for h in at.get("html") if "stSidebar" in h.proto.body]    # sidebar visible elsewhere


def test_try_an_example_link_opens_activision():
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["go"] = "example"
    at.run()
    assert at.sidebar.radio(key="mode").value == "Example & saved deals"
    assert at.title[0].value == "Microsoft Corporation / Activision Blizzard, Inc."
    assert not at.query_params                                        # cleared: a refresh stays put


def test_analyse_a_deal_link_opens_the_form():
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["go"] = "new"
    at.run()
    assert at.title[0].value == "New deal"
    assert not at.query_params


def test_unknown_go_parameter_is_ignored():
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["go"] = "nowhere"
    at.run()
    assert at.sidebar.radio(key="mode").value == "Home" and not at.exception


@pytest.mark.parametrize("deal", [ILLUSTRATIVE, ACTIVISION])
def test_disclaimer_always_shown(deal):
    at = run_app(deal)
    assert not at.sidebar.caption                                     # sidebar holds navigation only
    assert DISCLAIMER in [c.value for c in at.main.caption]           # footer of every deal section


def test_illustrative_headline_tiles_match_locked_outputs():
    assert tiles(run_app(ILLUSTRATIVE)) == {
        "Enterprise value": "$6,800m", "Equity value": "$6,000m",
        "Premium": "20.0%", "EV / EBITDA": "13.60x"}


def test_activision_headline_tiles_match_locked_outputs():
    assert tiles(run_app(ACTIVISION)) == {
        "Enterprise value": "$68,824m", "Equity value": "$75,597m",
        "Premium": "45.3%", "EV / EBITDA": "20.39x"}


def test_deal_terms():
    at = run_app(ACTIVISION)
    terms = dict(table_with(at, "Term", "Offer price per share").values) \
        | dict(table_with(at, "Term", "Fully diluted shares").values)
    assert terms["Offer price per share"] == "$95.00"
    assert terms["Unaffected share price"] == "$65.39 (close 2022-01-14)"
    assert terms["Fully diluted shares"] == "795.76m (treasury stock method)"
    assert terms["Financing mix (assumption)"] == "100% cash"


def test_warnings():
    at = run_app(ILLUSTRATIVE)
    assert not at.warning and not at.main.tabs[0].info
    assert "No warnings." in [c.value for c in at.caption]


def test_deliberately_empty_fields_are_notes_not_warnings():
    # The engine still warns (see test_activision.py); the app shows the _sources reason instead
    at = run_app(ACTIVISION)
    assert not at.main.tabs[0].warning
    assert "No warnings." in [c.value for c in at.main.tabs[0].caption]
    notes = [i.value for i in at.main.tabs[0].info]
    assert len(notes) == 2
    assert notes[0].startswith("stated_equity_value is intentionally empty: Deliberately left empty: "
                               "the \\$68.7bn headline is net of Activision's net cash")
    assert notes[1].startswith("tax_rate is intentionally empty: Not provided")


def test_unexplained_empty_field_stays_a_warning(tmp_path):
    # Same Activision file without the stated_equity_value reason -> it is no longer explained
    data = json.loads(ACTIVISION_FILE.read_text(encoding="utf-8"))
    del data["_sources"]["stated_equity_value"]
    path = tmp_path / "deal.json"
    path.write_text(json.dumps(data))
    analysis = analyse_transaction(load_deal(path))
    assert list(intentionally_empty(analysis, load_sources(path))) == ["tax_rate"]


def test_tags_keep_facts_assumptions_and_calculations_apart():
    at = run_app(ACTIVISION)
    financials = table_with(at, "Item", "Revenue").set_index("Item")["Tag"]
    assert financials["Revenue"] == "Fact"
    assert financials["EBITDA"] == "Fact · derived"            # built as EBIT + D&A, per _sources
    assert set(table_with(at, "Assumption", "Tax rate")["Tag"]) == {"Assumption"}
    synergies = table_with(at, "Metric", "Pro forma EBITDA").set_index("Metric")["Tag"]
    assert synergies["Pro forma EBITDA"] == "Calculated · uses assumptions"
    multiples = table_with(at, "Metric", "EV / EBITDA").set_index("Metric")
    assert multiples.loc["EV / EBITDA", "Tag"] == "Calculated"
    assert multiples.loc["EV / EBITDA", "Formula"] == "Transaction EV ÷ EBITDA"


def test_metric_notes_are_shown_in_full():
    captions = [c.value for c in run_app(ACTIVISION).caption]
    assert any(c.startswith("↳ Fully diluted shares: Treasury stock method at the offer price") for c in captions)


def test_sources_shown_for_real_deal_only():
    at = run_app(ACTIVISION)
    figures = table_with(at, "Field", "share_build.basic_shares").set_index("Field")
    assert figures.loc["share_build.basic_shares", "Page"] == "PDF p.151 / A-25"
    assert figures.loc["share_build.option_tranches[0].strike", "Value"] == "57.77"
    checks = table_with(at, "Check", "headline_transaction_value").set_index("Check")
    assert checks.loc["headline_transaction_value", "Published"] == "$68,700m"
    assert checks.loc["headline_transaction_value", "Our figure"] == "Transaction enterprise value: $68,824m"
    assert not at.main.tabs[1].info

    at = run_app(ILLUSTRATIVE)
    assert at.info[0].value == "No sources recorded for this deal."


def test_figure_detail_quotes_the_source_exactly():
    at = run_app(ACTIVISION)
    at.main.selectbox[0].select("total_debt").run()
    text = " ".join(m.value for m in at.main.markdown)
    # "$" escaped so markdown shows the filing text verbatim instead of a maths formula
    assert r"> Total gross long-term debt \$ 3,650 | Unamortized discount" in text
    assert "Note 13 Debt" in text


def test_dcf_tab_for_activision():
    at = run_app(ACTIVISION)
    assert tiles(at, 2) == {"DCF value per share": "$99.03", "DCF enterprise value": "$72,030m",
                            "Offer vs DCF value": "-4.1%", "Terminal value % of EV": "82.0%"}
    assert len(at.main.tabs[2].get("vega_lite_chart")) == 1            # the heatmap
    assert [w.value for w in at.main.tabs[2].warning] == [
        "Terminal value is 82% of DCF enterprise value: the valuation depends mostly on the perpetuity "
        "assumptions (WACC and g)."]
    schedule = table_with(at, "Year", 2022).set_index("Year")
    assert schedule.loc[2022, "Present value (calculated)"] == "$1,648m"


def test_dcf_tab_without_inputs():
    at = run_app(ILLUSTRATIVE)
    assert at.main.tabs[2].info[0].value.startswith("No DCF inputs for this deal.")


def test_valuation_tab_for_activision():
    at = run_app(ACTIVISION)
    tab = at.main.tabs[3]
    assert len(tab.get("vega_lite_chart")) == 1                                  # football field
    comps = table_with(at, "Method", "Trading comps (CY2022E EBITDA)").set_index("Method")
    assert comps.loc["Trading comps (CY2022E EBITDA)", "Implied value per share (calculated)"] == "$68.77 – $88.86"
    assert comps.loc["Precedent transactions (LTM EBITDA)", "Offer multiple"] == "19.04x"
    field = table_with(at, "Range", "Analyst price targets").set_index("Range")
    assert (field.loc["Analyst price targets", "Low"], field.loc["Analyst price targets", "High"]) == ("$54.00", "$125.00")


def test_valuation_caption_shows_dollar_prices_verbatim():
    captions = [c.value for c in run_app(ACTIVISION).main.tabs[3].caption]
    assert any(r"offer \$95.00; dashed line = unaffected price \$65.39" in c for c in captions)


def test_valuation_tab_without_inputs():
    assert run_app(ILLUSTRATIVE).main.tabs[3].info[0].value.startswith("No comps, precedents or DCF")
