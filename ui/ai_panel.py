"""
AI analyst tab (Step 6). The model only interprets the engine's outputs; every
statement it returns is checked (ai/analyst.py) before it is shown here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

import streamlit as st

from ai.analyst import AnalystUnavailable, ChatTurn, CheckedReport, ask_analyst, ask_question
from ai.payload import build_payload
from finance.comps import ValuationAnalysis
from finance.dcf import DCFAnalysis
from finance.models import TransactionAnalysis
from ui.settings import ai_session_limit, setting
from utils.formatting import md

# kind -> (badge label, colour); the badge makes the provenance of each sentence visible
KINDS = {"fact": ("Fact", "gray"), "assumption": ("Assumption", "orange"),
         "calculated": ("Calculated", "blue"), "interpretation": ("AI interpretation", "violet")}


def api_key() -> Optional[str]:
    """ANTHROPIC_API_KEY from .streamlit/secrets.toml, else the environment; None if neither is set."""
    return setting("ANTHROPIC_API_KEY")


def render_ai(analysis: TransactionAnalysis, sources: dict, dcf: Optional[DCFAnalysis],
              valuation: Optional[ValuationAnalysis], key_prefix: str) -> None:
    st.caption("Claude reads the engine's outputs (and nothing else) and writes a short interpretation, "
               "then answers your questions. It never calculates: every figure it writes is checked against "
               "the engine, and any sentence with a figure the engine did not produce is removed.")
    key = api_key()
    if not key:
        st.info("AI analyst unavailable: no API key configured. Add ANTHROPIC_API_KEY to "
                ".streamlit/secrets.toml (local) or the app's secrets (Streamlit Cloud). "
                "All other tabs work without it.")
        return

    payload = build_payload(analysis, sources, dcf, valuation)
    state_key = _state_key(payload, key_prefix)
    limit = ai_session_limit()
    if _requests_left(limit):
        if st.button("Generate AI analysis", type="primary", key=f"{key_prefix}_ai_button"):
            _count_request()
            with st.spinner("Claude is reviewing the engine outputs..."):
                try:
                    st.session_state[state_key] = ask_analyst(payload, key)
                except AnalystUnavailable as exc:
                    st.session_state[state_key] = str(exc)
            st.rerun()                        # redraw with the new count (hides the button at the cap)
        st.caption(f"AI requests used this session (analyses and questions): "
                   f"{st.session_state.get('ai_calls', 0)} of {limit}.")
    else:                                     # cap reached: no more calls, earlier results still shown
        st.info(f"This session has used its {limit} AI requests (analyses and questions; a cap that keeps the "
                f"public demo's API costs bounded). Reload the page to start a new session.")
    result = st.session_state.get(state_key)
    if isinstance(result, str):
        st.error(result)
    elif isinstance(result, CheckedReport):
        render_report(result)
    render_chat(payload, key, f"{state_key}_chat", limit)


def _requests_left(limit: int) -> bool:
    return st.session_state.get("ai_calls", 0) < limit


def _count_request() -> None:
    """Every Claude call (an analysis or a question) counts toward the per-session limit."""
    st.session_state.ai_calls = st.session_state.get("ai_calls", 0) + 1


def render_chat(payload: dict, key: str, chat_key: str, limit: int) -> None:
    """Questions about this deal, answered from the same payload and checked like the analysis."""
    st.subheader("Ask a question about this deal")
    st.caption("Answers use only the engine's outputs. Anything the engine has not calculated (for example a "
               "different WACC or offer price) is reported as unavailable rather than estimated.")
    history: list[ChatTurn] = st.session_state.setdefault(chat_key, [])
    for turn in history:
        with st.chat_message("user"):
            st.markdown(md(turn.question))
        with st.chat_message("assistant"):
            render_answer(turn)
    left = _requests_left(limit)
    question = st.chat_input("Ask a question about this deal" if left else "AI request limit reached for this session",
                             key=f"{chat_key}_input", disabled=not left)
    if question and left:
        _count_request()
        with st.spinner("Claude is answering from the engine outputs..."):
            history.append(ask_question(payload, list(history), question.strip(), key))
        st.rerun()


def render_answer(turn: ChatTurn) -> None:
    if turn.error:
        st.error(turn.error)
        return
    for s in turn.statements:
        _statement(s.text, s.kind)
    for u in turn.unavailable:
        c1, c2 = st.columns([1, 6], vertical_alignment="center")
        with c1:
            st.badge("Unavailable", color="gray")
        c2.markdown(md(u))
    if not turn.statements and not turn.unavailable:
        st.caption("No statement in this answer passed the number checker.")
    if turn.rejected:
        with st.expander(f"{len(turn.rejected)} statement(s) removed by the number checker"):
            for text, reason in turn.rejected:
                st.markdown(md(f"- ~~{text}~~  \n  *Reason: {reason}*"))


def _state_key(payload: dict, key_prefix: str) -> str:
    """One stored analysis per exact set of inputs (changing any input needs a new analysis)."""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return f"{key_prefix}_ai_{digest}"


def latest_report(analysis: TransactionAnalysis, sources: dict, dcf: Optional[DCFAnalysis],
                  valuation: Optional[ValuationAnalysis], key_prefix: str) -> Optional[CheckedReport]:
    """The checked AI report for these exact inputs, if one was generated this session."""
    result = st.session_state.get(_state_key(build_payload(analysis, sources, dcf, valuation), key_prefix))
    return result if isinstance(result, CheckedReport) else None


def render_report(r: CheckedReport) -> None:
    if r.headline:
        st.subheader("Headline")
        _statement(r.headline.text, r.headline.kind)
    section = None
    for s in r.statements:
        if s.section != section:
            section = s.section
            st.subheader(section)
        _statement(s.text, s.kind)
    if r.unavailable:
        st.subheader("Unavailable data")
        for u in r.unavailable:
            st.markdown(md(f"- {u}"))
    if r.rejected:
        with st.expander(f"{len(r.rejected)} statement(s) removed by the number checker"):
            for text, reason in r.rejected:
                st.markdown(md(f"- ~~{text}~~  \n  *Reason: {reason}*"))
    st.caption("AI interpretation of the engine's outputs. Verify against the Financials, DCF and Valuation "
               "tabs. Preliminary analytical tool for educational purposes. Not investment advice.")


def _statement(text: str, kind: str) -> None:
    label, colour = KINDS[kind]
    c1, c2 = st.columns([1, 6], vertical_alignment="center")
    with c1:
        st.badge(label, color=colour)
    c2.markdown(md(text))
