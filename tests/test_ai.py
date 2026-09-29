"""
Step 6 tests: the AI analyst's payload, number checker and statement checks.

No test calls the real Claude API: the client is replaced by a fake that returns
a prepared answer, so these run offline, cost nothing and are deterministic.
"""

from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from streamlit.testing.v1 import AppTest

from ai.analyst import AnalystReport, AnalystUnavailable, Statement, ask_analyst, check_report
from ai.number_checker import allowed_numbers, numbers_in, unsupported_numbers
from ai.payload import build_payload
from finance.comps import analyse_valuation
from finance.dcf import analyse_dcf
from finance.transaction import analyse_transaction
from utils.io import load_deal, load_sources

ROOT = Path(__file__).parent.parent
DEAL_FILE = ROOT / "data" / "sample_deals" / "microsoft_activision.json"


@pytest.fixture(scope="module")
def payload():
    deal = load_deal(DEAL_FILE)
    dcf = analyse_dcf(deal)
    return build_payload(analyse_transaction(deal), load_sources(DEAL_FILE), dcf, analyse_valuation(deal, dcf))


def item(payload, item_id):
    return next(i for i in payload["items"] if i["id"] == item_id)


def s(text, kind="interpretation", ids=()):
    return Statement(text=text, kind=kind, item_ids=list(ids))


def report(*statements, headline=None, unavailable=()):
    return AnalystReport(headline=headline or s("Microsoft is paying a full price.", ids=["premium"]),
                         valuation=list(statements), premium_and_market=[], risks_and_limitations=[],
                         unavailable=list(unavailable))


# ------------------------------------------------------------------ payload --

def test_payload_tags_every_item_with_its_provenance(payload):
    assert item(payload, "offer_price_per_share") == {
        "id": "offer_price_per_share", "label": "offer price per share", "display": "$95.00",
        "provenance": "fact", "formula": "", "source": "DEFM14A PDF p.2 / unnumbered"}
    assert item(payload, "enterprise_value")["display"] == "$68,824m"
    assert item(payload, "enterprise_value")["provenance"] == "calculated"
    assert item(payload, "pro_forma_ebitda")["provenance"] == "calculated_from_assumptions"
    assert item(payload, "dcf_wacc") ["provenance"] == "assumption"
    assert item(payload, "dcf_value_per_share")["display"] == "$99.03"
    assert item(payload, "multiple_0_low")["display"] == "$68.77"
    assert item(payload, "reference_1_high")["display"] == "$125.00"
    assert {i["provenance"] for i in payload["items"]} <= {"fact", "assumption", "calculated",
                                                          "calculated_from_assumptions"}


def test_payload_lists_unavailable_data_with_reasons(payload):
    joined = " ".join(payload["unavailable"])
    assert "stated_equity_value: Deliberately left empty" in joined
    assert "tax_rate: Not provided" in joined
    assert "after_tax_synergies" in joined


def test_payload_without_dcf_or_comps():
    deal = load_deal(ROOT / "tests" / "fixtures" / "illustrative_deal.json")
    p = build_payload(analyse_transaction(deal), {})
    assert "DCF: no forecast, WACC or terminal growth provided" in p["unavailable"]
    assert "Trading comps / precedent transactions: not provided" in p["unavailable"]


# ----------------------------------------------------------- number checker --

def test_numbers_in():
    assert numbers_in("EV of $68,824m is 20.39x CY2022E EBITDA; offer -4.1% vs DCF") == \
        ["68,824", "20.39", "2022", "4.1"]


def test_unsupported_numbers(payload):
    allowed = allowed_numbers(payload)
    assert unsupported_numbers("EV is $68,824m, or 20.39x EBITDA; premium 45.3%.", allowed) == []
    assert unsupported_numbers("The offer is $95 per share.", allowed) == []            # 95 = 95.00
    assert unsupported_numbers("The offer is 4.1% below the DCF value.", allowed) == []  # sign ignored
    assert unsupported_numbers("EV is about $68.8bn.", allowed) == ["68.8"]            # converted: rejected
    assert unsupported_numbers("Synergies could reach $2,000m.", allowed) == ["2,000"]  # invented: rejected


# ---------------------------------------------------------- statement checks --

def test_valid_statements_pass(payload):
    r = check_report(report(
        s("The offer implies EV of $68,824m.", "calculated", ["enterprise_value"]),
        s("The offer price is $95.00 per share.", "fact", ["offer_price_per_share"]),
        s("The DCF uses a WACC of 7.25%.", "assumption", ["dcf_wacc"]),
        s("The price looks full against trading comps.", "interpretation", ["multiple_0_high"])), payload)
    assert not r.rejected
    assert [x.kind for x in r.statements] == ["calculated", "fact", "assumption", "interpretation"]
    assert r.headline.text == "Microsoft is paying a full price."


@pytest.mark.parametrize("statement, reason", [
    (s("EV is roughly $69bn.", "calculated", ["enterprise_value"]), "not produced by the engine: 69"),
    (s("EV is $68,824m.", "calculated", ["made_up_id"]), "cites unknown item(s): made_up_id"),
    (s("EV is $68,824m.", "fact", ["enterprise_value"]), "tagged as fact but does not rely only on reported facts"),
    (s("The offer is $95.00.", "calculated", ["offer_price_per_share"]), "tagged as calculated"),
    (s("The offer is $95.00.", "assumption", ["offer_price_per_share"]), "tagged as assumption but cites no"),
    (s("Revenue is strong.", "fact", []), "tagged as fact but does not rely only on reported facts"),
])
def test_invalid_statements_are_removed_with_reason(payload, statement, reason):
    r = check_report(report(statement), payload)
    assert not r.statements
    assert len(r.rejected) == 1 and reason in r.rejected[0][1]


def test_bad_headline_and_unavailable_items_are_filtered(payload):
    r = check_report(report(headline=s("A 50% premium.", "calculated", ["premium"]),
                            unavailable=["Acquirer financials", "Synergy estimate of 500"]), payload)
    assert r.headline is None and "not produced by the engine: 50" in r.rejected[0][1]
    assert r.unavailable == ["Acquirer financials"]


# ------------------------------------------------------------------- the call --

class FakeClient:
    """Stands in for anthropic.Anthropic(): records the request, returns a prepared response."""
    def __init__(self, response=None, error=None):
        self.request, self._response, self._error = None, response, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.request = kwargs
        if self._error:
            raise self._error
        return self._response


def test_ask_analyst_sends_only_the_payload_and_checks_the_answer(payload):
    answer = report(s("EV is $68,824m.", "calculated", ["enterprise_value"]),
                    s("EV is about $70bn.", "calculated", ["enterprise_value"]))
    client = FakeClient(SimpleNamespace(stop_reason="end_turn", parsed_output=answer))
    r = ask_analyst(payload, "key", client=client)
    assert client.request["model"] == "claude-opus-5-5"
    assert client.request["output_format"] is AnalystReport
    assert client.request["fallbacks"] == "default"
    assert '"id": "enterprise_value"' in client.request["messages"][0]["content"]
    assert [x.text for x in r.statements] == ["EV is $68,824m."]
    assert r.rejected[0][0] == "EV is about $70bn."


@pytest.mark.parametrize("response, error, message", [
    (SimpleNamespace(stop_reason="refusal", parsed_output=None), None, "declined"),
    (SimpleNamespace(stop_reason="max_tokens", parsed_output=None), None, "incomplete"),
    (None, anthropic.AuthenticationError("bad key", response=httpx2.Response(
        401, request=httpx2.Request("POST", "https://api.anthropic.com")), body=None), "API key was rejected"),
    (None, anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")),
     "Could not reach"),
])
def test_failures_become_readable_messages(payload, response, error, message):
    with pytest.raises(AnalystUnavailable, match=message):
        ask_analyst(payload, "key", client=FakeClient(response, error))


# ---------------------------------------------------------------------- app --

def test_app_without_api_key_says_unavailable(isolated_deal_folders, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ui.ai_panel.api_key", lambda: None)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.sidebar.selectbox[0].select("Microsoft Corporation / Activision Blizzard, Inc.").run()
    assert at.main.tabs[4].info[0].value.startswith("AI analyst unavailable: no API key configured.")
