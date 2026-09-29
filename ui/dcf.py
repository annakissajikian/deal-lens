"""
DCF tab (Step 4): valuation summary, cash-flow schedule and the WACC × terminal
growth sensitivity heatmap. Display only: every number comes from finance.dcf.

Heatmap colour = polarity against the offer price (diverging scale):
blue = DCF value above the offer, red = below, neutral grey = at the offer.
"""

from __future__ import annotations

from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

from finance.dcf import DCFAnalysis
from finance.models import TransactionAnalysis
from utils.formatting import format_value, md

# Reference diverging palette, dark-mode steps: blue <-> red poles with a neutral grey midpoint.
BELOW_OFFER, AT_OFFER, ABOVE_OFFER = "#e66767", "#383835", "#3987e5"
INK, MUTED = "#FFFFFF", "rgba(255,255,255,0.55)"


def render_dcf(analysis: TransactionAnalysis, dcf: Optional[DCFAnalysis]) -> None:
    if dcf is None:
        st.info("No DCF inputs for this deal. Add a forecast, WACC and terminal growth in the "
                "New deal form (DCF group) to value it.")
        return
    deal, cur = analysis.inputs, analysis.inputs.info.currency
    d = deal.dcf

    # Short tile labels (the full labels are in the Valuation table below)
    tiles = {"dcf_value_per_share": "DCF value per share", "dcf_enterprise_value": "DCF enterprise value",
             "offer_vs_dcf": "Offer vs DCF value", "tv_share_of_ev": "Terminal value % of EV"}
    for col, (key, label) in zip(st.columns(len(tiles)), tiles.items()):
        m = dcf.metrics[key]
        col.metric(label, format_value(m.value, m.unit, cur), help=f"{m.label} = {m.formula}", border=True)
    st.caption(f"Offer price {format_value(deal.facts.offer_price_per_share, 'per_share', cur)} · "
               f"valuation date {d.valuation_date or 'not stated'} · end-of-year discounting · "
               f"every DCF figure depends on the assumptions below")

    st.subheader("Assumptions")
    st.dataframe(pd.DataFrame([
        ("WACC (discount rate)", format_value(d.wacc, "percent_2", cur), "Assumption"),
        ("Terminal growth (perpetuity)", format_value(d.terminal_growth, "percent_2", cur), "Assumption"),
        ("Forecast years", f"{d.forecast_years[0]}–{d.forecast_years[-1]}", "Assumption"),
        ("Valuation date", d.valuation_date or "Not stated", "Assumption"),
    ], columns=["Input", "Value", "Tag"]), hide_index=True)

    st.subheader("Cash-flow schedule")
    st.dataframe(pd.DataFrame([
        (row["year"], format_value(row["fcf"], "currency", cur), f"{row['discount_factor']:.4f}",
         format_value(row["pv"], "currency", cur)) for row in dcf.schedule],
        columns=["Year", "Unlevered FCF (assumption)", "Discount factor", "Present value (calculated)"]),
        hide_index=True)

    st.subheader("Valuation")
    st.dataframe(pd.DataFrame([
        (m.label, format_value(m.value, m.unit, cur), m.formula, "Calculated · uses assumptions")
        for m in dcf.metrics.values()], columns=["Metric", "Value", "Formula", "Tag"]), hide_index=True)
    for m in dcf.metrics.values():
        if m.note:
            st.caption(md(f"↳ {m.label}: {m.note}"))

    st.subheader("Sensitivity: value per share")
    low, high = dcf.grid_range()
    on_grid = d.wacc in dcf.wacc_axis and d.terminal_growth in dcf.growth_axis
    base_note = ("Outlined cell = base case." if on_grid else
                 f"The base case (WACC {d.wacc:.2%}, g {d.terminal_growth:.2%}) = "
                 f"{format_value(dcf.value('dcf_value_per_share'), 'per_share', cur)} lies between the grid points.")
    st.caption(md(f"Rows: WACC · columns: terminal growth · range {format_value(low, 'per_share', cur)} to "
                  f"{format_value(high, 'per_share', cur)}. Blue = above the "
                  f"{format_value(deal.facts.offer_price_per_share, 'per_share', cur)} offer, red = below, "
                  f"grey = at the offer. {base_note}"))
    st.altair_chart(heatmap(dcf, deal.facts.offer_price_per_share, cur, d.wacc, d.terminal_growth))
    with st.expander("Sensitivity as a table"):
        st.dataframe(pd.DataFrame(
            [[format_value(v, "per_share", cur) for v in row] for row in dcf.grid],
            index=[f"WACC {w:.2%}" for w in dcf.wacc_axis],
            columns=[f"g {g:.2%}" for g in dcf.growth_axis]))

    st.subheader("Warnings")
    for w in dcf.warnings:
        st.warning(md(w))
    if not dcf.warnings:
        st.caption("No warnings.")


def heatmap(dcf: DCFAnalysis, offer: float, cur: str, base_wacc: float, base_growth: float) -> alt.LayerChart:
    rows = []
    for i, w in enumerate(dcf.wacc_axis):
        for j, g in enumerate(dcf.growth_axis):
            v, vs = dcf.grid[i][j], dcf.grid_offer_vs[i][j]
            rows.append({"WACC": f"{w:.2%}", "Terminal growth": f"{g:.2%}", "value": v,
                         "label": format_value(v, "per_share", cur),
                         "offer_vs": "n.m." if vs is None else f"{vs:+.1%}",
                         "base": abs(w - base_wacc) < 1e-9 and abs(g - base_growth) < 1e-9})
    df = pd.DataFrame(rows)
    values = [v for v in df["value"] if pd.notna(v)]
    spread = max(abs(max(values) - offer), abs(min(values) - offer)) or 1.0
    # On the dark theme every cell (dark grey midpoint to coloured poles) takes white text
    df["text_colour"] = INK

    x = alt.X("Terminal growth:O", sort=None, axis=alt.Axis(labelAngle=0, title="Terminal growth (g)"))
    y = alt.Y("WACC:O", sort=None, axis=alt.Axis(title="WACC"))
    tooltip = [alt.Tooltip("WACC:O"), alt.Tooltip("Terminal growth:O"),
               alt.Tooltip("label:N", title="Value per share"), alt.Tooltip("offer_vs:N", title="Offer vs DCF")]
    cells = alt.Chart(df).mark_rect(stroke="#08060E", strokeWidth=2, cornerRadius=4).encode(
        x=x, y=y, tooltip=tooltip,
        color=alt.Color("value:Q", title="Value per share",
                        scale=alt.Scale(domain=[offer - spread, offer, offer + spread],
                                        range=[BELOW_OFFER, AT_OFFER, ABOVE_OFFER], interpolate="lab")))
    base = alt.Chart(df[df["base"]]).mark_rect(fill=None, stroke=INK, strokeWidth=2.5, cornerRadius=4).encode(
        x=x, y=y)
    labels = alt.Chart(df).mark_text(fontSize=13).encode(
        x=x, y=y, text="label:N", color=alt.Color("text_colour:N", scale=None, legend=None), tooltip=tooltip)
    # Each layer keeps its own colour scale: a shared scale (Vega's default) mixes the numeric
    # heatmap scale with the literal text colours and the chart silently renders at zero height.
    return (cells + base + labels).resolve_scale(color="independent").properties(
        height=46 * len(dcf.wacc_axis) + 40)
