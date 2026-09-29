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

from finance.comps import analyse_valuation
from finance.dcf import analyse_dcf
from finance.models import DealInputError
from finance.transaction import analyse_transaction
from ui.ai_panel import latest_report, render_ai
from ui.dcf import render_dcf
from ui.financials import render_financials
from ui.memo_panel import render_memo
from ui.overview import render_overview
from ui.valuation import render_valuation
from utils.formatting import SYMBOLS, md
from reports.memo import build_memo
from utils.io import deal_from_dict

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
    "DCF": ("dcf",),
    "Valuation": ("valuation",),
}
# Editable tables: form key -> columns. Their rows live in st.session_state, not in widgets.
TABLES = {
    "option_tranches": {"number": float, "strike": float},
    "dcf_rows": {"year": float, "fcf": float},
    "val_methods": {"name": str, "method": str, "metric_label": str, "metric_value": float,
                    "multiple_low": float, "multiple_high": float},
    "val_peers": {"valuation": str, "peer": str, "multiple": float},
    "val_refs": {"name": str, "low": float, "high": float},
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
    "dcf_include": False, "dcf_rows": [], "dcf_wacc": None, "dcf_terminal_growth": None,
    "dcf_valuation_date": "", "dcf_wacc_range": "", "dcf_growth_range": "",
    "val_methods": [], "val_peers": [], "val_refs": [],
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
    deal = {
        "_comment": f"Entered via the DealLens form on {date.today().isoformat()}. "
                    f"Figures are not source-verified.",
        "deal": {"acquirer": v["acquirer"].strip(), "target": v["target"].strip(),
                 "sector": v["sector"].strip(), "announcement_date": d.isoformat() if d else None,
                 "currency": v["currency"]},
        "facts": facts,
        "assumptions": {k: pct(v[k]) if k in PERCENT_FIELDS else v[k]
                        for k in ("cost_synergies", "revenue_synergies") + PERCENT_FIELDS},
    }
    if v["dcf_include"]:
        rows = [r for r in v["dcf_rows"] if r.get("year") is not None or r.get("fcf") is not None]
        year = lambda y: int(y) if isinstance(y, float) and y.is_integer() else y
        deal["dcf"] = {"forecast_years": [year(r.get("year")) for r in rows],
                       "unlevered_fcf": [r.get("fcf") for r in rows],
                       "wacc": pct(v["dcf_wacc"]), "terminal_growth": pct(v["dcf_terminal_growth"]),
                       "valuation_date": v["dcf_valuation_date"].strip(),
                       "wacc_range": percent_list(v["dcf_wacc_range"]),
                       "growth_range": percent_list(v["dcf_growth_range"])}
    methods = [r for r in v["val_methods"] if any(x is not None for x in r.values())]
    refs = [r for r in v["val_refs"] if any(x is not None for x in r.values())]
    if methods or refs:
        multiples = []
        for r in methods:
            entry = {k: r.get(k) for k in ("name", "method", "metric_label", "metric_value")}
            peers = [{"name": p.get("peer"), "multiple": p.get("multiple")} for p in v["val_peers"]
                     if p.get("valuation") == r.get("name") and (p.get("peer") or p.get("multiple") is not None)]
            if peers:
                entry["peers"] = peers
            for k in ("multiple_low", "multiple_high"):
                if r.get(k) is not None:
                    entry[k] = r[k]
            multiples.append(entry)
        deal["valuation"] = {"multiples": multiples,
                             "references": [{k: r.get(k) for k in ("name", "low", "high")} for r in refs]}
    return deal


def orphan_peers(v: dict) -> list[str]:
    """Peer rows whose 'valuation' does not match any method name (they would be ignored)."""
    names = {r.get("name") for r in v["val_methods"]}
    return [p.get("peer") or "(unnamed)" for p in v["val_peers"]
            if (p.get("peer") or p.get("multiple") is not None) and p.get("valuation") not in names]


def percent_list(text: str) -> list:
    """'6.5, 7, 7.5' -> [0.065, 0.07, 0.075]; a token that is not a number becomes None (-> error)."""
    out = []
    for token in (t.strip() for t in text.split(",") if t.strip()):
        try:
            out.append(round(float(token) / 100, 10))
        except ValueError:
            out.append(None)
    return out


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
    val = raw.get("valuation")
    if val:
        v["val_methods"] = [{k: m.get(k) for k in TABLES["val_methods"]} for m in val.get("multiples", [])]
        v["val_peers"] = [{"valuation": m.get("name"), "peer": p.get("name"), "multiple": p.get("multiple")}
                          for m in val.get("multiples", []) for p in m.get("peers", [])]
        v["val_refs"] = [{k: r.get(k) for k in TABLES["val_refs"]} for r in val.get("references", [])]
    dcf = raw.get("dcf")
    if dcf:
        as_pct = lambda x: None if x is None else round(x * 100, 10)
        v.update(dcf_include=True,
                 dcf_rows=[{"year": y, "fcf": c} for y, c in zip(dcf.get("forecast_years", []),
                                                                   dcf.get("unlevered_fcf", []))],
                 dcf_wacc=as_pct(dcf.get("wacc")), dcf_terminal_growth=as_pct(dcf.get("terminal_growth")),
                 dcf_valuation_date=dcf.get("valuation_date", ""),
                 dcf_wacc_range=", ".join(f"{as_pct(x):g}" for x in dcf.get("wacc_range", [])),
                 dcf_growth_range=", ".join(f"{as_pct(x):g}" for x in dcf.get("growth_range", [])))
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
    v = {k: st.session_state.get(f"f_{k}", saved[k]) for k in BLANK if k not in TABLES}
    for name, columns in TABLES.items():
        table = st.session_state.get(f"f_table_{name}")
        v[name] = saved[name] if table is None else [
            {c: _cell(row[c], kind) for c, kind in columns.items()} for _, row in table.iterrows()]
    return v


def _cell(x, kind):
    """Table cell -> None (blank), float or stripped text."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return None
    if kind is float:
        return float(x)
    return str(x).strip() or None


def _load(values: dict) -> None:
    """Put `values` into the form (on first use and for 'Start from')."""
    for k, val in values.items():
        if k not in TABLES:
            st.session_state[f"f_{k}"] = val
    st.session_state.f_saved = dict(values)
    for name in TABLES:
        st.session_state[f"f_table_{name}"] = None
    st.session_state.f_version = st.session_state.get("f_version", 0) + 1   # fresh tables


def _table_editor(name: str, column_config: dict) -> None:
    """Editable table whose rows survive reruns (see the note above _values)."""
    key = f"f_{name}_{st.session_state.f_version}"
    if key not in st.session_state:          # table (re)drawn: start from the saved rows
        st.session_state[f"f_base_{name}"] = st.session_state.f_saved[name]
    columns = TABLES[name]
    base = pd.DataFrame(st.session_state[f"f_base_{name}"] or [], columns=list(columns))
    base = base.astype({c: ("float64" if kind is float else "object") for c, kind in columns.items()})
    st.session_state[f"f_table_{name}"] = st.data_editor(
        base, key=key, num_rows="dynamic", hide_index=True, column_config=column_config)


def _start_from(deals: dict) -> None:
    choice = st.session_state.f_start
    if choice == "Blank":
        _load(BLANK)
    else:
        _load(form_values_from_dict(json.loads(deals[choice].read_text(encoding="utf-8"))))


def _run() -> None:
    raw = build_deal_dict(_values())
    try:
        deal = deal_from_dict(raw)
        dcf = analyse_dcf(deal)
        st.session_state.f_result = (raw, analyse_transaction(deal), dcf, analyse_valuation(deal, dcf))
        st.session_state.f_errors = []
    except DealInputError as exc:
        st.session_state.f_result, st.session_state.f_errors = None, exc.errors


def _group_errors(group: str) -> None:
    for e in errors_by_group(st.session_state.f_errors)[group]:
        st.error(md(e))


def render_deal_form(deals: dict) -> None:
    if "f_saved" not in st.session_state:
        _load(BLANK)
        st.session_state.update(f_errors=[], f_result=None)
    for k, val in st.session_state.f_saved.items():            # restore values Streamlit dropped
        if k not in TABLES and f"f_{k}" not in st.session_state:
            st.session_state[f"f_{k}"] = val

    st.title("New deal")
    st.caption("Enter the deal, press Run analysis, then review the results tabs. "
               "Percentages are typed as 25 for 25%. Leave optional fields blank if not available.")
    # Own key + default: otherwise Streamlit reuses the saved-deal view's active "Deal Overview" tab
    inputs_tab, overview_tab, financials_tab, dcf_tab, valuation_tab, ai_tab, memo_tab = st.tabs(
        ["Inputs", "Deal Overview", "Financials", "DCF", "Valuation", "AI analyst", "Memo"],
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
            _table_editor("option_tranches", {
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

        st.subheader("DCF · assumptions (optional)")
        st.checkbox("Include a DCF valuation", key="f_dcf_include")
        if st.session_state.f_dcf_include:
            c1, c2, c3 = st.columns(3)
            c1.number_input("WACC, %", key="f_dcf_wacc", value=None, format="%.2f")
            c2.number_input("Terminal growth, %", key="f_dcf_terminal_growth", value=None, format="%.2f")
            c3.text_input("Valuation date", key="f_dcf_valuation_date", help="e.g. 2025-12-31")
            c1, c2 = st.columns(2)
            c1.text_input("Heatmap WACC values, % (optional)", key="f_dcf_wacc_range",
                          help="Comma-separated, e.g. 6.5, 7, 7.5, 8. Blank = WACC ± 1% in 0.5% steps.")
            c2.text_input("Heatmap growth values, % (optional)", key="f_dcf_growth_range",
                          help="Comma-separated, e.g. 2.25, 2.5, 2.75. Blank = g ± 0.5% in 0.25% steps.")
            st.caption("Forecast: one row per year (consecutive years), unlevered free cash flow in millions.")
            _table_editor("dcf_rows", {
                "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                "fcf": st.column_config.NumberColumn("Unlevered FCF (m)", format="%.2f")})
        _group_errors("DCF")

        st.subheader("Comps, precedents and reference ranges · assumptions (optional)")
        st.caption("One row per valuation method. Leave the multiple range blank to use the interquartile "
                   "range (25th–75th percentile) of that method's peers below.")
        _table_editor("val_methods", {
            "name": st.column_config.TextColumn("Method name", help="e.g. Trading comps (LTM EBITDA)"),
            "method": st.column_config.SelectboxColumn("Type", options=["comps", "precedents"]),
            "metric_label": st.column_config.TextColumn("Target metric", help="e.g. LTM EBITDA"),
            "metric_value": st.column_config.NumberColumn("Metric value (m)", format="%.2f"),
            "multiple_low": st.column_config.NumberColumn("Multiple low (x)", format="%.2f"),
            "multiple_high": st.column_config.NumberColumn("Multiple high (x)", format="%.2f")})
        st.caption("Peers: the method name must match a row above exactly.")
        _table_editor("val_peers", {
            "valuation": st.column_config.TextColumn("Method name"),
            "peer": st.column_config.TextColumn("Peer company or transaction"),
            "multiple": st.column_config.NumberColumn("Multiple (x)", format="%.2f")})
        orphans = orphan_peers(_values())
        if orphans:
            st.warning("These peers do not match any method name and will be ignored: " + ", ".join(orphans))
        st.caption("Per-share reference ranges, e.g. 52-week trading range or analyst price targets.")
        _table_editor("val_refs", {
            "name": st.column_config.TextColumn("Range name"),
            "low": st.column_config.NumberColumn("Low (per share)", format="%.2f"),
            "high": st.column_config.NumberColumn("High (per share)", format="%.2f")})
        _group_errors("Valuation")

        st.button("Run analysis", type="primary", on_click=_run)

    st.session_state.f_saved = _values()
    result = st.session_state.f_result
    current = build_deal_dict(st.session_state.f_saved)
    stale = result is not None and {k: x for k, x in result[0].items() if k != "_comment"} != \
        {k: x for k, x in current.items() if k != "_comment"}
    with inputs_tab:
        if result is not None and not stale:
            st.success("Analysis ready: see the Deal Overview and Financials tabs.")
            _render_export(result)
        elif stale:
            st.info("Inputs have changed since the last run: press Run analysis to update the results.")

    for tab, render in ((overview_tab, lambda r: render_overview(r[1], NO_SOURCES)),
                        (financials_tab, lambda r: render_financials(r[1], NO_SOURCES)),
                        (dcf_tab, lambda r: render_dcf(r[1], r[2])),
                        (valuation_tab, lambda r: render_valuation(r[3], r[0]["deal"]["currency"])),
                        (ai_tab, lambda r: render_ai(r[1], NO_SOURCES, r[2], r[3], key_prefix="form")),
                        (memo_tab, lambda r: render_memo(r[1], NO_SOURCES, r[2], r[3], key_prefix="form"))):
        with tab:
            if result is None or stale:
                st.info("Run the analysis from the Inputs tab to see results here.")
            else:
                render(result)


def _render_export(result: tuple) -> None:
    """Download the deal memo for the analysis just run (built by reports/memo.py)."""
    _, analysis, dcf, valuation = result
    ai = latest_report(analysis, NO_SOURCES, dcf, valuation, key_prefix="form")
    memo = build_memo(analysis, NO_SOURCES, dcf, valuation, ai)
    st.subheader("Export")
    st.download_button("Download deal memo (Word)", data=memo.docx, file_name=f"{memo.filename_stem}.docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", type="primary", key="f_memo_docx")
    st.caption("A preliminary deal memo built from these results: transaction summary, financials, DCF, "
               "football field, warnings and limitations" + (", and your AI analyst view." if ai else ". "
               "Generate the AI analysis first to include the AI analyst view.") +
               " Word can save it as PDF. More formats in the Memo tab.")
