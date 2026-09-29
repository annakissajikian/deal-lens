"""
DealLens web app (Steps 3 and 3b).

    streamlit run app.py

Two modes, chosen in the sidebar:
  * Analyse a saved deal: any file in data/sample_deals/ or data/user_deals/
  * Enter a new deal: the input form in ui/deal_form.py

The app only displays results: every number comes from analyse_transaction()
in finance/. Nothing is calculated here.
"""

import streamlit as st

from finance.comps import analyse_valuation
from finance.dcf import analyse_dcf
from finance.models import DealInputError
from finance.transaction import analyse_transaction
from ui.dcf import render_dcf
from ui.deal_form import render_deal_form
from ui.financials import render_financials
from ui.overview import render_overview
from ui.valuation import render_valuation
from utils.formatting import md
from utils.io import USER_DEALS_DIR, list_sample_deals, load_deal, load_sources

DISCLAIMER = "Preliminary analytical tool for educational purposes. Not investment advice."
MODES = ("Analyse a saved deal", "Enter a new deal")

st.set_page_config(page_title="DealLens", layout="wide")

deals = list_sample_deals() | {f"Saved: {label}": path
                               for label, path in list_sample_deals(USER_DEALS_DIR).items()}
with st.sidebar:
    st.markdown("## DealLens")
    st.caption("Preliminary M&A analysis")
    mode = st.radio("Mode", MODES, key="mode")
    label = st.selectbox("Deal", list(deals)) if mode == MODES[0] and deals else None
    st.divider()
    st.caption(DISCLAIMER)


def show_saved_deal(label: str) -> None:
    try:
        deal = load_deal(deals[label])
        analysis = analyse_transaction(deal)
    except DealInputError as exc:
        st.error(md(f"{deals[label].name} cannot be analysed:\n\n" + "\n".join(f"- {e}" for e in exc.errors)))
        return
    info = deal.info
    st.title(f"{info.acquirer} / {info.target}")
    announced = info.announcement_date.strftime("%d %b %Y") if info.announcement_date else "date not provided"
    st.caption(f"{info.sector} · Announced {announced} · {info.currency} millions · "
               f"Financials {deal.facts.financials_period}")
    sources = load_sources(deals[label])
    dcf = analyse_dcf(deal)
    overview_tab, financials_tab, dcf_tab, valuation_tab = st.tabs(
        ["Deal Overview", "Financials", "DCF", "Valuation"])
    with overview_tab:
        render_overview(analysis, sources)
    with financials_tab:
        render_financials(analysis, sources)
    with dcf_tab:
        render_dcf(analysis, dcf)
    with valuation_tab:
        render_valuation(analyse_valuation(deal, dcf), info.currency)


if mode == MODES[1]:
    render_deal_form(deals)
elif label is None:
    st.error("No deal files found in data/sample_deals/ or data/user_deals/.")
else:
    show_saved_deal(label)

st.divider()
st.caption(DISCLAIMER)
