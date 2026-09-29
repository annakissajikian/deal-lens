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
    at.sidebar.radio(key="mode").set_value("Example & saved deals").run()
    at.sidebar.selectbox[0].select("Example: Microsoft Corporation / Activision Blizzard, Inc.").run()
    assert at.main.tabs[4].info[0].value.startswith("AI analyst unavailable: no API key configured.")


# ------------------------------------------------------------------ settings --

def test_settings_read_secrets_or_environment(monkeypatch):
    from ui import settings
    monkeypatch.setattr(settings, "setting", lambda name: {"DEALLENS_AI_SESSION_LIMIT": "5"}.get(name))
    assert settings.ai_session_limit() == 5
    monkeypatch.setattr(settings, "setting", lambda name: None)
    assert settings.ai_session_limit() == 3                                            # default
    monkeypatch.setattr(settings, "setting", lambda name: "lots")
    assert settings.ai_session_limit() == 3                                            # invalid -> default


def test_ai_analyses_are_capped_per_session(isolated_deal_folders, monkeypatch):
    calls = []
    def fake(payload, key):                              # stands in for the API call
        calls.append(1)
        return check_report(report(), payload)
    monkeypatch.setattr("ui.ai_panel.api_key", lambda: "test-key")
    monkeypatch.setattr("ui.ai_panel.ask_analyst", fake)
    monkeypatch.setattr("ui.ai_panel.ai_session_limit", lambda: 1)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.sidebar.radio(key="mode").set_value("Example & saved deals").run()
    at.sidebar.selectbox[0].select("Example: Microsoft Corporation / Activision Blizzard, Inc.").run()
    next(b for b in at.button if b.label == "Generate AI analysis").click().run()
    assert len(calls) == 1
    tab = at.main.tabs[4]
    assert any("has used its 1 AI requests" in i.value for i in tab.info)
    assert not [b for b in at.button if b.label == "Generate AI analysis"]    # no way past the cap
    assert any(m.value == "Microsoft is paying a full price." for m in tab.markdown)   # result still shown


# -------------------------------------------------------------------- chat --

from ai.analyst import ChatAnswer, ChatTurn, CheckedStatement, ask_question, chat_messages, check_answer


def answer(*statements, unavailable=()):
    return ChatAnswer(statements=list(statements), unavailable=list(unavailable))


def test_chat_answer_is_checked_like_the_analysis(payload):
    turn = check_answer("What is the EV?", answer(
        s("The transaction EV is $68,824m.", "calculated", ["enterprise_value"]),
        s("That is roughly $69bn.", "calculated", ["enterprise_value"]),
        unavailable=["A DCF at a WACC of 9% has not been calculated by the engine.",
                     "Acquirer financials are not in the payload."]), payload)
    assert [x.text for x in turn.statements] == ["The transaction EV is $68,824m."]
    assert turn.rejected == [("That is roughly $69bn.", "contains figure(s) not produced by the engine: 69")]
    # a number from the question (9%) is not an engine figure either, so that line is dropped too
    assert turn.unavailable == ["Acquirer financials are not in the payload."]


def test_history_carries_only_checked_answers():
    first = ChatTurn("What is the premium?",
                     statements=[CheckedStatement("Answer", "The premium is 45.3%.", "calculated", ["premium"])],
                     rejected=[("About 45%.", "contains figure(s) not produced by the engine: 45")],
                     unavailable=["Acquirer share price"])
    failed = ChatTurn("And the synergies?", error="Could not reach the Claude API.")
    assert chat_messages([first, failed], "Is the offer full?") == [
        {"role": "user", "content": "What is the premium?"},
        {"role": "assistant", "content": "[calculated] The premium is 45.3%.\n[unavailable] Acquirer share price"},
        {"role": "user", "content": "And the synergies?"},
        {"role": "assistant", "content": "(No answer: Could not reach the Claude API.)"},
        {"role": "user", "content": "Is the offer full?"}]           # rejected "About 45%" never goes back


def test_ask_question_sends_payload_and_history(payload):
    client = FakeClient(SimpleNamespace(stop_reason="end_turn", parsed_output=answer(
        s("The offer is 4.1% below the DCF value.", "calculated", ["offer_vs_dcf"]))))
    history = [ChatTurn("What is the EV?", statements=[
        CheckedStatement("Answer", "The EV is $68,824m.", "calculated", ["enterprise_value"])])]
    turn = ask_question(payload, history, "How does the offer compare with the DCF?", "key", client=client)
    req = client.request
    assert req["model"] == "claude-opus-5-5" and req["output_format"] is ChatAnswer
    assert req["fallbacks"] == "default"
    assert '"id": "enterprise_value"' in req["system"][1]["text"]                 # same tagged payload
    assert req["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert [m["role"] for m in req["messages"]] == ["user", "assistant", "user"]
    assert req["messages"][-1]["content"] == "How does the offer compare with the DCF?"
    assert [x.text for x in turn.statements] == ["The offer is 4.1% below the DCF value."]


def test_ask_question_never_raises(payload):
    turn = ask_question(payload, [], "Hi", "key", client=FakeClient(
        None, anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))))
    assert turn.error.startswith("Could not reach") and not turn.statements


def deal_ai_tab(monkeypatch, limit, calls):
    """Activision's AI tab with a fake analyst and a fake chat (no API calls)."""
    def fake_question(payload, history, question, key):
        calls.append((question, [t.question for t in history]))
        return check_answer(question, answer(s("The EV is $68,824m.", "calculated", ["enterprise_value"])), payload)
    monkeypatch.setattr("ui.ai_panel.api_key", lambda: "test-key")
    monkeypatch.setattr("ui.ai_panel.ask_question", fake_question)
    monkeypatch.setattr("ui.ai_panel.ask_analyst", lambda payload, key: check_report(report(), payload))
    monkeypatch.setattr("ui.ai_panel.ai_session_limit", lambda: limit)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.sidebar.radio(key="mode").set_value("Example & saved deals").run()
    at.sidebar.selectbox[0].select("Example: Microsoft Corporation / Activision Blizzard, Inc.").run()
    return at


def test_chat_in_the_app(isolated_deal_folders, monkeypatch):
    calls = []
    at = deal_ai_tab(monkeypatch, 5, calls)
    tab = at.main.tabs[4]
    assert "Ask a question about this deal" in [h.value for h in tab.subheader]
    at.chat_input[0].set_value("What is the EV?").run()
    at.chat_input[0].set_value("And the premium?").run()
    assert calls == [("What is the EV?", []), ("And the premium?", ["What is the EV?"])]   # history passed
    tab = at.main.tabs[4]
    assert [m.name for m in tab.chat_message] == ["user", "assistant", "user", "assistant"]
    assert any(m.value == r"The EV is \$68,824m." for m in tab.markdown)   # "$" escaped for markdown
    assert any("AI requests used this session (analyses and questions): 2 of 5" in c.value for c in tab.caption)


def test_questions_count_toward_the_session_limit(isolated_deal_folders, monkeypatch):
    calls = []
    at = deal_ai_tab(monkeypatch, 2, calls)
    next(b for b in at.button if b.label == "Generate AI analysis").click().run()     # request 1
    at.chat_input[0].set_value("What is the EV?").run()                              # request 2
    assert len(calls) == 1
    assert at.chat_input[0].disabled                                                  # no request 3
    assert not [b for b in at.button if b.label == "Generate AI analysis"]
    assert any("has used its 2 AI requests" in i.value for i in at.main.tabs[4].info)
