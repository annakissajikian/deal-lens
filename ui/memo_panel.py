"""
Memo tab (Step 7): generate the preliminary deal memo and download it.
The memo itself is built deterministically in reports/memo.py.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from finance.comps import ValuationAnalysis
from finance.dcf import DCFAnalysis
from finance.models import TransactionAnalysis
from reports.memo import build_memo
from ui.ai_panel import latest_report
from utils.formatting import md


def render_memo(analysis: TransactionAnalysis, sources: dict, dcf: Optional[DCFAnalysis],
                valuation: Optional[ValuationAnalysis], key_prefix: str) -> None:
    ai = latest_report(analysis, sources, dcf, valuation, key_prefix)
    st.caption("A preliminary deal memo built from the engine outputs: transaction summary, target financials, "
               "DCF, football field, warnings and limitations, sources"
               + (", plus the AI analyst view you generated." if ai else
                  ". Generate the AI analysis first to include the AI analyst view."))
    memo_key = f"{key_prefix}_memo"
    if st.button("Generate Deal Memo", type="primary", key=f"{key_prefix}_memo_button"):
        st.session_state[memo_key] = build_memo(analysis, sources, dcf, valuation, ai)
    memo = st.session_state.get(memo_key)
    if memo is None or memo.title != f"{analysis.inputs.info.acquirer} / {analysis.inputs.info.target}":
        return
    c1, c2, _ = st.columns([1, 1, 2])
    c1.download_button("Download memo (HTML, print to PDF)", memo.html, file_name=f"{memo.filename_stem}.html",
                       mime="text/html", key=f"{key_prefix}_memo_html")
    c2.download_button("Download memo (Markdown)", memo.markdown, file_name=f"{memo.filename_stem}.md",
                       mime="text/markdown", key=f"{key_prefix}_memo_md")
    with st.container(border=True):
        st.markdown(md(memo.markdown))
