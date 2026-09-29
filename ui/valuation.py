"""
Valuation tab (Step 5): football field, trading comps and precedent transactions.
Display only: every number comes from finance.comps and finance.dcf.

Football field colours = identity of the method (categorical palette, fixed
order, so a method keeps its colour whichever methods a deal has).
"""

from __future__ import annotations

from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

from finance.comps import ValuationAnalysis
from utils.formatting import format_value, md

CATEGORIES = ["DCF", "Trading comps", "Precedent transactions", "Market reference"]
CATEGORY_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]      # reference palette slots 1-4
INK, MUTED = "#0b0b0b", "#52514e"


def render_valuation(v: Optional[ValuationAnalysis], cur: str) -> None:
    if v is None or not v.bars:
        st.info("No comps, precedents or DCF for this deal. Add them in the New deal form "
                "(Valuation and DCF groups).")
        return
    per_share = lambda x: format_value(x, "per_share", cur)

    st.subheader("Football field: value per share")
    st.caption(md(f"Each bar is a per-share value range. Solid line = offer {per_share(v.offer_price)}; "
                  f"dashed line = unaffected price {per_share(v.unaffected_price)}."))
    st.altair_chart(football_field(v, cur))
    with st.expander("Football field as a table"):
        st.dataframe(pd.DataFrame([(b.label, b.category, per_share(b.low), per_share(b.high)) for b in v.bars],
                                  columns=["Range", "Method", "Low", "High"]), hide_index=True)

    if v.multiples:
        st.subheader("Trading comps and precedent transactions")
        st.dataframe(pd.DataFrame([(
            m.source.name, f"{m.source.metric_label}: {format_value(m.source.metric_value, 'currency', cur)}",
            f"{m.multiple_low:.1f}x – {m.multiple_high:.1f}x", m.range_basis.capitalize(),
            f"{format_value(m.ev_low, 'currency', cur)} – {format_value(m.ev_high, 'currency', cur)}",
            f"{per_share(m.per_share_low)} – {per_share(m.per_share_high)}",
            format_value(m.offer_multiple, "multiple", cur)) for m in v.multiples],
            columns=["Method", "Target metric (input)", "Multiple range (assumption)", "Range basis",
                     "Implied EV (calculated)", "Implied value per share (calculated)", "Offer multiple"]),
            hide_index=True)
        st.caption("Implied EV = multiple × target metric · per share = (implied EV − net debt) ÷ fully diluted "
                   "shares · offer multiple = transaction EV ÷ target metric.")
        for m in v.multiples:
            if m.source.peers:
                with st.expander(f"Peers: {m.source.name}"):
                    st.dataframe(pd.DataFrame([(p.name, format_value(p.multiple, "multiple", cur))
                                               for p in m.source.peers], columns=["Peer", "Multiple"]),
                                 hide_index=True)
                    st.caption(f"Min {m.peer_min:.2f}x · median {m.peer_median:.2f}x · mean {m.peer_mean:.2f}x · "
                               f"max {m.peer_max:.2f}x")


def football_field(v: ValuationAnalysis, cur: str) -> alt.LayerChart:
    df = pd.DataFrame([{"Range": b.label, "Method": b.category, "low": b.low, "high": b.high,
                        "low_label": format_value(b.low, "per_share", cur),
                        "high_label": format_value(b.high, "per_share", cur)} for b in v.bars])
    lo = min(df["low"].min(), v.unaffected_price, v.offer_price)
    hi = max(df["high"].max(), v.unaffected_price, v.offer_price)
    pad = (hi - lo) * 0.12
    x = alt.X("low:Q", title="Value per share", scale=alt.Scale(domain=[lo - pad, hi + pad], zero=False),
              axis=alt.Axis(format="$,.0f", grid=True, gridColor="#e1e0d9"))
    y = alt.Y("Range:N", sort=None, title=None, axis=alt.Axis(labelLimit=260))
    tooltip = [alt.Tooltip("Range:N"), alt.Tooltip("Method:N"),
               alt.Tooltip("low_label:N", title="Low"), alt.Tooltip("high_label:N", title="High")]
    bars = alt.Chart(df).mark_bar(cornerRadius=4, height=22).encode(
        x=x, x2="high:Q", y=y, tooltip=tooltip,
        color=alt.Color("Method:N", scale=alt.Scale(domain=CATEGORIES, range=CATEGORY_COLOURS),
                        legend=alt.Legend(orient="bottom", title=None)))
    low_text = alt.Chart(df).mark_text(align="right", dx=-6, color=INK, fontSize=12).encode(
        x="low:Q", y=y, text="low_label:N")
    high_text = alt.Chart(df).mark_text(align="left", dx=6, color=INK, fontSize=12).encode(
        x="high:Q", y=y, text="high_label:N")
    lines = pd.DataFrame([{"price": v.offer_price, "name": f"Offer {format_value(v.offer_price, 'per_share', cur)}",
                           "dash": "solid"},
                          {"price": v.unaffected_price,
                           "name": f"Unaffected {format_value(v.unaffected_price, 'per_share', cur)}",
                           "dash": "dashed"}])
    offer = alt.Chart(lines[lines["dash"] == "solid"]).mark_rule(color=INK, strokeWidth=2).encode(x="price:Q")
    unaffected = alt.Chart(lines[lines["dash"] == "dashed"]).mark_rule(
        color=MUTED, strokeWidth=1.5, strokeDash=[5, 4]).encode(x="price:Q")
    line_labels = alt.Chart(lines).mark_text(align="left", dx=4, dy=-8, color=INK, fontSize=12, fontWeight="bold",
                                             baseline="bottom").encode(x="price:Q", y=alt.value(0), text="name:N")
    # Lines before labels, so value labels stay readable where a line crosses them
    return (bars + offer + unaffected + low_text + high_text + line_labels).properties(
        height=44 * len(df) + 30)
