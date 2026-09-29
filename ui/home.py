"""Landing page (Step 8): what DealLens is, and one click into a deal."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import streamlit as st

ASSETS = Path(__file__).parent.parent / "assets"

FEATURES = [
    ("Transaction & DCF engine",
     "Equity value, EV, premium and multiples; fully diluted shares by the treasury stock method; "
     "a DCF with a WACC × growth sensitivity heatmap. All calculated in Python and tested by hand."),
    ("Comps & football field",
     "Trading comps and precedent transactions turned into per-share ranges and lined up against the "
     "offer price on a football field."),
    ("AI analyst & deal memo",
     "Claude interprets the results, never calculates, and a number checker removes any figure the "
     "engine did not produce. One click exports a deal memo."),
]


def render_home(on_new_deal: Callable[[], None], on_example: Optional[Callable[[], None]]) -> None:
    left, _ = st.columns([3, 2])
    with left:
        st.image(str(ASSETS / "logo_mark.svg"), width=72)
        st.title("DealLens")
        st.markdown("#### Preliminary M&A analysis in minutes: valuation, premium and a deal memo, with every "
                    "figure calculated in Python and traced to its source.")
        c1, c2 = st.columns(2)
        c1.button("Analyse a deal", type="primary", on_click=on_new_deal, width="stretch")
        if on_example:
            c2.button("Try the example: Microsoft / Activision", on_click=on_example, width="stretch")
    st.write("")
    for col, (title, text) in zip(st.columns(len(FEATURES)), FEATURES):
        with col.container(border=True, height="stretch"):
            st.markdown(f"**{title}**")
            st.caption(text)
    st.write("")
    st.caption("Facts, assumptions, calculated figures and AI interpretation are labelled everywhere. "
               "The example deal is sourced from Activision Blizzard's 10-K and merger proxy, with page references.")
