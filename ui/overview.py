"""Deal Overview tab: headline tiles, deal terms and warnings."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from finance.dilution import diluted_share_count
from finance.models import TransactionAnalysis
from utils.formatting import format_value, md

HEADLINE_METRICS = ("enterprise_value", "equity_value", "premium", "ev_ebitda")


def render_overview(analysis: TransactionAnalysis, sources: dict) -> None:
    deal = analysis.inputs
    info, f, a, cur = deal.info, deal.facts, deal.assumptions, deal.info.currency

    # Headline tiles (the formula shows as a tooltip)
    for col, key in zip(st.columns(len(HEADLINE_METRICS)), HEADLINE_METRICS):
        m = analysis.metrics[key]
        col.metric(m.label, format_value(m.value, m.unit, cur), help=m.formula, border=True)

    st.subheader("Deal terms")
    unaffected_date = sources["sources"].get("unaffected_share_price", {}).get("as_of")
    method = "treasury stock method" if f.share_build is not None else "entered"
    mix = " · ".join(f"{share:.0%} {name}" for name, share in
                     (("cash", a.financing_cash), ("debt", a.financing_debt), ("stock", a.financing_stock))
                     if share)
    terms = [
        ("Acquirer", info.acquirer),
        ("Target", info.target),
        ("Sector", info.sector),
        ("Announcement date", info.announcement_date.isoformat() if info.announcement_date else "Not provided"),
        ("Offer price per share", format_value(f.offer_price_per_share, "per_share", cur)),
        ("Unaffected share price", format_value(f.unaffected_share_price, "per_share", cur)
         + (f" (close {unaffected_date})" if unaffected_date else "")),
        ("Fully diluted shares", f"{format_value(diluted_share_count(f), 'shares', cur)} ({method})"),
        ("Financing mix (assumption)", mix),
        ("Financials period", f.financials_period),
        ("Currency", f"{cur}, amounts in millions"),
    ]
    left, right = st.columns(2)
    half = (len(terms) + 1) // 2
    for col, rows in ((left, terms[:half]), (right, terms[half:])):
        col.dataframe(pd.DataFrame(rows, columns=["Term", "Value"]), hide_index=True)

    # A "not provided" warning whose field the deal's _sources explains as deliberately
    # empty is shown as a neutral note with that reason, not as a warning.
    reasons = intentionally_empty(analysis, sources)
    explained = {field: w for w in analysis.warnings for field in reasons if f"'{field}' not provided" in w}
    st.subheader("Warnings")
    open_warnings = [w for w in analysis.warnings if w not in explained.values()]
    for w in open_warnings:
        st.warning(md(w))
    if not open_warnings:
        st.caption("No warnings.")
    for field in explained:
        st.info(md(f"{field} is intentionally empty: {reasons[field]}"))


def intentionally_empty(analysis: TransactionAnalysis, sources: dict) -> dict[str, str]:
    """Fields that are empty (None) and whose _sources entry gives a note explaining why."""
    deal = analysis.inputs
    return {field: s["note"] for field, s in sources["sources"].items()
            if s.get("note") and getattr(deal.facts, field, getattr(deal.assumptions, field, 0)) is None}
