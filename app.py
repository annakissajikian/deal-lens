"""
DealLens web app.

    streamlit run app.py

Three sections, chosen in the sidebar:
  * Home: landing page (ui/home.py)
  * Example & saved deals: data/sample_deals/ ("Example: ...") and data/user_deals/ ("Saved: ...")
  * New deal: the input form in ui/deal_form.py

The app only displays results: every number comes from analyse_transaction()
in finance/. Nothing is calculated here.
"""

import streamlit as st

from finance.comps import analyse_valuation
from finance.dcf import analyse_dcf
from finance.models import DealInputError
from finance.transaction import analyse_transaction
from ui.ai_panel import render_ai
from ui.dcf import render_dcf
from ui.deal_form import render_deal_form
from ui.financials import render_financials
from ui.home import ASSETS, example_stats, render_home
from ui.memo_panel import render_memo
from ui.overview import render_overview
from ui.valuation import render_valuation
from utils.formatting import md
from utils.io import USER_DEALS_DIR, list_sample_deals, load_deal, load_sources

DISCLAIMER = "Preliminary analytical tool for educational purposes. Not investment advice."
MODES = ("Home", "Example & saved deals", "New deal")
EXAMPLE_FILE = "microsoft_activision.json"

st.set_page_config(page_title="DealLens", page_icon=":material/query_stats:", layout="wide")
st.logo(str(ASSETS / "logo_wordmark.svg"), icon_image=str(ASSETS / "logo_mark.svg"), size="large")

deals = {f"Example: {label}": path for label, path in list_sample_deals().items()} | \
        {f"Saved: {label}": path for label, path in list_sample_deals(USER_DEALS_DIR).items()}
example = next((label for label, path in deals.items() if path.name == EXAMPLE_FILE), None)


# Landing-page links carry ?go=new / ?go=example (HTML cannot call Streamlit callbacks).
# Apply it before the sidebar widgets are drawn, then clear it so a refresh stays put.
go = st.query_params.get("go")
if go == "new":
    st.session_state.mode = MODES[2]
elif go == "example" and example:
    st.session_state.mode, st.session_state.deal = MODES[1], example
if go:
    st.query_params.clear()


with st.sidebar:
    st.caption("Preliminary M&A analysis")
    mode = st.radio("Section", MODES, key="mode")
    label = st.selectbox("Deal", list(deals), key="deal") if mode == MODES[1] and deals else None
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
    valuation = analyse_valuation(deal, dcf)
    overview_tab, financials_tab, dcf_tab, valuation_tab, ai_tab, memo_tab = st.tabs(
        ["Deal Overview", "Financials", "DCF", "Valuation", "AI analyst", "Memo"])
    with overview_tab:
        render_overview(analysis, sources)
    with financials_tab:
        render_financials(analysis, sources)
    with dcf_tab:
        render_dcf(analysis, dcf)
    with valuation_tab:
        render_valuation(valuation, info.currency)
    with ai_tab:
        render_ai(analysis, sources, dcf, valuation, key_prefix="saved")
    with memo_tab:
        render_memo(analysis, sources, dcf, valuation, key_prefix="saved")


if mode == MODES[0]:
    render_home(example_stats(deals.get(example)), example.removeprefix("Example: ") if example else "")
elif mode == MODES[2]:
    render_deal_form(deals)
elif label is None:
    st.error("No deal files found in data/sample_deals/ or data/user_deals/.")
else:
    show_saved_deal(label)

st.divider()
st.caption(DISCLAIMER)
