"""
New deal mode (Step 3b): enter a deal in grouped fields, run it, download or save it.

The form builds the same dict as a deal JSON file and runs it through
utils.io.deal_from_dict(), so it cannot bypass any validation. The only
conversion here is units: percentages are typed as 25 for 25% and stored as
0.25, as everywhere else in DealLens.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd
import streamlit as st

from finance.models import DealInputError
from finance.transaction import analyse_transaction
from ui.financials import render_financials
from ui.overview import render_overview
from utils.formatting import SYMBOLS, md
from utils.io import deal_filename, deal_from_dict, save_deal

PERCENT_FIELDS = ("revenue_synergy_incremental_margin", "financing_cash", "financing_debt",
                  "financing_stock", "tax_rate")
NO_SOURCES = {"documents": {}, "sources": {}, "cross_checks": {}}

# Group -> field names, used to place each validation error under its group.
GROUPS = {
    "Deal info": ("acquirer", "target", "sector", "announcement_date", "currency"),
    "Deal terms": ("offer_price_per_share", "unaffected_share_price"),
    "Share count": ("diluted_shares_outstanding", "share_build", "basic_shares", "rsus", "option_tranches"),
    "Target financials": ("revenue", "ebitda", "ebit", "net_income", "total_debt", "cash",
                          "stated_equity_value", "financials_period"),
    "Assumptions": ("cost_synergies", "revenue_synergies", "Financing mix") + PERCENT_FIELDS,
}

BLANK = {
    "acquirer": "", "target": "", "sector": "", "announcement_date": None, "currency": "USD",
    "offer_price_per_share": None, "unaffected_share_price": None,
    "share_mode": "Enter fully diluted shares", "diluted_shares_outstanding": None,
    "basic_shares": None, "rsus": None, "as_of": "", "option_tranches": [],
    "financials_period": "LTM", "revenue": None, "ebitda": None, "ebit": None, "net_income": None,
    "total_debt": None, "cash": None, "stated_equity_value": None,
    "cost_synergies": 0.0, "revenue_synergies": 0.0, "revenue_synergy_incremental_margin": None,
    "financing_cash": 100.0, "financing_debt": 0.0, "financing_stock": 0.0, "tax_rate": None,
}
SHARE_MODES = ("Enter fully diluted shares", "Build with treasury stock method")


# ------------------------------------------------------- pure conversions --

def build_deal_dict(v: dict) -> dict:
    """Form values -> deal JSON dict. Blank stays null (never 0); 25 (%) becomes 0.25."""
    pct = lambda x: None if x is None else round(x / 100, 10)
    facts = {k: v[k] for k in ("offer_price_per_share", "unaffected_share_price", "revenue", "ebitda",
                               "ebit", "net_income", "total_debt", "cash", "stated_equity_value",
                               "financials_period")}
    if v["share_mode"] == SHARE_MODES[1]:
        build = {"basic_shares": v["basic_shares"],
                 "option_tranches": [{"number": t.get("number"), "strike": t.get("strike")}
                                     for t in v["option_tranches"]
                                     if t.get("number") is not None or t.get("strike") is not None]}
        if v["rsus"] is not None:                       # blank = no RSUs (the model default is 0)
            build["rsus"] = v["rsus"]
        if v["as_of"].strip():
            build["as_of"] = v["as_of"].strip()
        facts["share_build"] = build
    else:
        facts["diluted_shares_outstanding"] = v["diluted_shares_outstanding"]
    d = v["announcement_date"]
    return {
        "_comment": f"Entered via the DealLens form on {date.today().isoformat()}. "
                    f"Figures are not source-verified.",
        "deal": {"acquirer": v["acquirer"].strip(), "target": v["target"].strip(),
                 "sector": v["sector"].strip(), "announcement_date": d.isoformat() if d else None,
                 "currency": v["currency"]},
        "facts": facts,
        "assumptions": {k: pct(v[k]) if k in PERCENT_FIELDS else v[k]
                        for k in ("cost_synergies", "revenue_synergies") + PERCENT_FIELDS},
    }


def form_values_from_dict(raw: dict) -> dict:
    """Deal JSON dict -> form values (the reverse of build_deal_dict), for 'Start from'."""
    info, facts, a = raw.get("deal", {}), raw.get("facts", {}), raw.get("assumptions", {})
    v = dict(BLANK)
    v.update({k: info[k] for k in ("acquirer", "target", "sector", "currency") if k in info})
    if info.get("announcement_date"):
        v["announcement_date"] = date.fromisoformat(info["announcement_date"])
    v.update({k: facts[k] for k in BLANK if k in facts})
    build = facts.get("share_build")
    if build:
        v.update(share_mode=SHARE_MODES[1], basic_shares=build.get("basic_shares"),
                 rsus=build.get("rsus"), as_of=build.get("as_of", ""),
                 option_tranches=[dict(t) for t in build.get("option_tranches", [])])
    for k in ("cost_synergies", "revenue_synergies") + PERCENT_FIELDS:
        if k in a:
            v[k] = round(a[k] * 100, 10) if k in PERCENT_FIELDS and a[k] is not None else a[k]
    return v


def errors_by_group(errors: list[str]) -> dict[str, list[str]]:
    """Place each error under every group whose field name it mentions (whole words only)."""
    placed: dict[str, list[str]] = {g: [] for g in GROUPS}
    for e in errors:
        for group, names in GROUPS.items():
            if any(re.search(rf"\b{re.escape(n)}\b", e) for n in names):
                placed[group].append(e)
    return placed


# -------------------------------------------------------------- streamlit --
# Streamlit deletes a widget's value when the widget is not drawn (e.g. the other
# share-count method, or while a saved deal is shown). A plain copy of every value,
# st.session_state.f_saved, is kept and used to restore missing widget values.

def _values() -> dict:
    saved = st.session_state.f_saved
    v = {k: st.session_state.get(f"f_{k}", saved[k]) for k in BLANK if k != "option_tranches"}
    table = st.session_state.get("f_table")
    v["option_tranches"] = saved["option_tranches"] if table is None else [
        {c: (None if pd.isna(row[c]) else float(row[c])) for c in ("number", "strike")}
        for _, row in table.iterrows()]
    return v


def _load(values: dict) -> None:
    """Put `values` into the form (on first use and for 'Start from')."""
    for k, val in values.items():
        if k != "option_tranches":
            st.session_state[f"f_{k}"] = val
    st.session_state.f_saved = dict(values)
    st.session_state.f_table = None
    st.session_state.f_version = st.session_state.get("f_version", 0) + 1   # fresh tranche table


def _start_from(deals: dict) -> None:
    choice = st.session_state.f_start
    if choice == "Blank":
        _load(BLANK)
    else:
        _load(form_values_from_dict(json.loads(deals[choice].read_text(encoding="utf-8"))))


def _run() -> None:
    raw = build_deal_dict(_values())
    st.session_state.f_save_msg = None
    try:
        st.session_state.f_result = (raw, analyse_transaction(deal_from_dict(raw)))
        st.session_state.f_errors = []
    except DealInputError as exc:
        st.session_state.f_result, st.session_state.f_errors = None, exc.errors


def _save() -> None:
    raw = st.session_state.f_result[0]
    try:
        path = save_deal(raw, overwrite=st.session_state.get("f_overwrite", False))
        st.session_state.f_save_msg = ("success", f"Saved to data/user_deals/{path.name}. "
                                                  f"It now appears in the saved-deal dropdown.")
    except FileExistsError as exc:
        st.session_state.f_save_msg = ("error", f"{exc} Tick 'Overwrite' to replace it.")


def _group_errors(group: str) -> None:
    for e in errors_by_group(st.session_state.f_errors)[group]:
        st.error(md(e))


def render_deal_form(deals: dict) -> None:
    if "f_saved" not in st.session_state:
        _load(BLANK)
        st.session_state.update(f_errors=[], f_result=None, f_save_msg=None)
    for k, val in st.session_state.f_saved.items():            # restore values Streamlit dropped
        if k != "option_tranches" and f"f_{k}" not in st.session_state:
            st.session_state[f"f_{k}"] = val

    st.title("New deal")
    st.caption("Enter the deal, press Run analysis, then review the results tabs. "
               "Percentages are typed as 25 for 25%. Leave optional fields blank if not available.")
    # Own key + default: otherwise Streamlit reuses the saved-deal view's active "Deal Overview" tab
    inputs_tab, overview_tab, financials_tab = st.tabs(["Inputs", "Deal Overview", "Financials"],
                                                       key="f_tabs", default="Inputs")

    with inputs_tab:
        st.selectbox("Start from", ["Blank"] + list(deals), key="f_start",
                     on_change=_start_from, args=(deals,))
        if st.session_state.f_errors:
            st.error(md(f"The deal cannot be analysed ({len(st.session_state.f_errors)} problem(s)):\n\n"
                        + "\n".join(f"- {e}" for e in st.session_state.f_errors)
                        + "\n\nPercentages are checked as decimals, so 25% appears as 0.25 in messages."))

        st.subheader("Deal info")
        c1, c2, c3 = st.columns(3)
        c1.text_input("Acquirer", key="f_acquirer")
        c2.text_input("Target", key="f_target")
        c3.text_input("Sector", key="f_sector")
        c1, c2, _ = st.columns(3)
        c1.date_input("Announcement date (optional)", key="f_announcement_date", format="YYYY-MM-DD")
        c2.selectbox("Currency", list(SYMBOLS), key="f_currency")
        _group_errors("Deal info")

        st.subheader("Deal terms · facts")
        c1, c2, _ = st.columns(3)
        c1.number_input("Offer price per share", key="f_offer_price_per_share", value=None, format="%.2f")
        c2.number_input("Unaffected share price", key="f_unaffected_share_price", value=None, format="%.2f",
                        help="Undisturbed close before the announcement.")
        _group_errors("Deal terms")

        st.subheader("Share count · facts (millions)")
        st.radio("Method", SHARE_MODES, key="f_share_mode", horizontal=True)
        if st.session_state.f_share_mode == SHARE_MODES[0]:
            st.number_input("Fully diluted shares outstanding", key="f_diluted_shares_outstanding", value=None,
                            format="%.6f")
        else:
            c1, c2, c3 = st.columns(3)
            c1.number_input("Basic shares outstanding", key="f_basic_shares", value=None, format="%.6f")
            c2.number_input("RSUs / PSUs (blank if none)", key="f_rsus", value=None, format="%.6f",
                            help="Unvested units; PSUs at target.")
            c3.text_input("As of (dates of the counts)", key="f_as_of")
            st.caption("Option tranches: one row per exercise-price range (millions of options, "
                       "weighted-average strike). Add rows with the + below the table.")
            key = f"f_tranches_{st.session_state.f_version}"
            if key not in st.session_state:        # table (re)drawn: start from the saved rows
                st.session_state.f_table_base = st.session_state.f_saved["option_tranches"]
            base = pd.DataFrame(st.session_state.f_table_base or [], columns=["number", "strike"], dtype=float)
            st.session_state.f_table = st.data_editor(
                base, key=key, num_rows="dynamic", hide_index=True, column_config={
                    "number": st.column_config.NumberColumn("Options (m)", format="%.6f"),
                    "strike": st.column_config.NumberColumn("Strike", format="%.2f")})
        _group_errors("Share count")

        st.subheader("Target financials · facts (millions)")
        c1, c2, c3, c4 = st.columns(4)
        c1.text_input("Period", key="f_financials_period", help="e.g. FY2025 or LTM")
        c2.number_input("Revenue", key="f_revenue", value=None, format="%.2f")
        c3.number_input("EBITDA", key="f_ebitda", value=None, format="%.2f")
        c4.number_input("EBIT (optional)", key="f_ebit", value=None, format="%.2f")
        c1, c2, c3, c4 = st.columns(4)
        c1.number_input("Net income (optional)", key="f_net_income", value=None, format="%.2f")
        c2.number_input("Total debt", key="f_total_debt", value=None, format="%.2f")
        c3.number_input("Cash", key="f_cash", value=None, format="%.2f")
        c4.number_input("Stated equity value (optional)", key="f_stated_equity_value", value=None, format="%.2f",
                        help="Headline equity value, used only as a cross-check.")
        _group_errors("Target financials")

        st.subheader("Assumptions")
        c1, c2, c3, c4 = st.columns(4)
        c1.number_input("Cost synergies (run-rate, m)", key="f_cost_synergies", value=None, format="%.2f")
        c2.number_input("Revenue synergies (run-rate, m)", key="f_revenue_synergies", value=None, format="%.2f")
        c3.number_input("Incremental margin, % (optional)", key="f_revenue_synergy_incremental_margin", value=None,
                        format="%.2f", help="Blank = target EBITDA margin is assumed (flagged).")
        c4.number_input("Tax rate, % (optional)", key="f_tax_rate", value=None, format="%.2f")
        c1, c2, c3, _ = st.columns(4)
        c1.number_input("Financed with cash, %", key="f_financing_cash", value=None, format="%.2f")
        c2.number_input("Financed with debt, %", key="f_financing_debt", value=None, format="%.2f")
        c3.number_input("Financed with stock, %", key="f_financing_stock", value=None, format="%.2f")
        _group_errors("Assumptions")

        st.button("Run analysis", type="primary", on_click=_run)

    st.session_state.f_saved = _values()
    result = st.session_state.f_result
    current = build_deal_dict(st.session_state.f_saved)
    stale = result is not None and {k: x for k, x in result[0].items() if k != "_comment"} != \
        {k: x for k, x in current.items() if k != "_comment"}
    with inputs_tab:
        if result is not None and not stale:
            st.success("Analysis ready: see the Deal Overview and Financials tabs.")
            _render_export(result[0])
        elif stale:
            st.info("Inputs have changed since the last run: press Run analysis to update the results.")

    for tab, render in ((overview_tab, lambda a: render_overview(a, NO_SOURCES)),
                        (financials_tab, lambda a: render_financials(a, NO_SOURCES))):
        with tab:
            if result is None or stale:
                st.info("Run the analysis from the Inputs tab to see results here.")
            else:
                render(result[1])


def _render_export(raw: dict) -> None:
    st.subheader("Export")
    c1, c2 = st.columns(2)
    c1.download_button("Download deal as JSON", data=json.dumps(raw, indent=2, ensure_ascii=False),
                       file_name=deal_filename(raw), mime="application/json")
    with c2:
        st.checkbox("Overwrite if the file already exists", key="f_overwrite")
        st.button(f"Save to data/user_deals/{deal_filename(raw)}", on_click=_save)
    msg = st.session_state.f_save_msg
    if msg:
        (st.success if msg[0] == "success" else st.error)(msg[1])
