"""
DealLens web app (Step 3).

    streamlit run app.py

The app only displays results: every number comes from analyse_transaction()
in finance/. Nothing is calculated here.
"""

import streamlit as st

from finance.models import DealInputError
from finance.transaction import analyse_transaction
from ui.financials import render_financials
from ui.overview import render_overview
from utils.io import list_sample_deals, load_deal, load_sources

DISCLAIMER = "Preliminary analytical tool for educational purposes. Not investment advice."

st.set_page_config(page_title="DealLens", layout="wide")

deals = list_sample_deals()
with st.sidebar:
    st.markdown("## DealLens")
    st.caption("Preliminary M&A analysis")
    label = st.selectbox("Deal", list(deals)) if deals else None
    st.divider()
    st.caption(DISCLAIMER)

if label is None:
    st.error("No deal files found in data/sample_deals/.")
    st.stop()

try:
    deal = load_deal(deals[label])
    analysis = analyse_transaction(deal)
except DealInputError as exc:
    st.error(f"{deals[label].name} cannot be analysed:\n\n" + "\n".join(f"- {e}" for e in exc.errors))
    st.stop()

info = deal.info
st.title(f"{info.acquirer} / {info.target}")
announced = info.announcement_date.strftime("%d %b %Y") if info.announcement_date else "date not provided"
st.caption(f"{info.sector} · Announced {announced} · {info.currency} millions · "
           f"Financials {deal.facts.financials_period}")

sources = load_sources(deals[label])
overview_tab, financials_tab = st.tabs(["Deal Overview", "Financials"])
with overview_tab:
    render_overview(analysis, sources)
with financials_tab:
    render_financials(analysis, sources)

st.divider()
st.caption(DISCLAIMER)
