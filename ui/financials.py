"""
Financials tab: target financials, assumptions, calculated metrics and sources.

Every row carries a tag so facts, assumptions and calculated figures stay
distinguishable:
    Fact                          reported in a filing (DealFacts)
    Fact · derived                built from filing figures, e.g. EBITDA = EBIT + D&A
    Assumption                    user judgement (DealAssumptions)
    Calculated                    engine output from facts only
    Calculated · uses assumptions engine output that depends on an assumption
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from finance.models import DealInputs, TransactionAnalysis
from utils.formatting import format_value, md

PROJECT_ROOT = Path(__file__).parent.parent
URL = re.compile(r"https?://\S+")
EVIDENCE_FILE = re.compile(r"data/sources/\S+\.(?:png|jpg|jpeg)")
# Fixed pixel widths so the tables line up with each other; other columns share the rest.
COLUMN_WIDTHS = {"Item": 260, "Assumption": 260, "Metric": 260, "Value": 120, "Formula": 380}

FINANCIALS = (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("ebit", "EBIT (operating income)"),
              ("net_income", "Net income"), ("total_debt", "Total debt"), ("cash", "Cash"))
ASSUMPTIONS = (("cost_synergies", "Cost synergies (run-rate)", "currency"),
               ("revenue_synergies", "Revenue synergies (run-rate)", "currency"),
               ("revenue_synergy_incremental_margin", "Incremental margin on revenue synergies", "percent"),
               ("financing_cash", "Financed with cash", "percent"),
               ("financing_debt", "Financed with debt", "percent"),
               ("financing_stock", "Financed with stock", "percent"),
               ("tax_rate", "Tax rate", "percent"))


def render_financials(analysis: TransactionAnalysis, sources: dict) -> None:
    deal = analysis.inputs
    cur, provenance, notes = deal.info.currency, deal.provenance(), sources["sources"]

    st.subheader(f"Target financials ({deal.facts.financials_period})")
    rows = []
    for field, label in FINANCIALS:
        value = getattr(deal.facts, field)
        derived = notes.get(field, {}).get("note", "").startswith("CALCULATED")
        tag = provenance[field].capitalize() + (" · derived" if derived else "")
        rows.append((label, format_value(value, "currency", cur) if value is not None else "Not provided", tag))
    _table(rows, ["Item", "Value", "Tag"])

    st.subheader("Assumptions")
    rows = [(label, format_value(getattr(deal.assumptions, field), unit, cur)
             if getattr(deal.assumptions, field) is not None else "Not provided",
             provenance[field].capitalize())
            for field, label, unit in ASSUMPTIONS]
    _table(rows, ["Assumption", "Value", "Tag"])

    st.subheader("Calculated metrics")
    sections: dict[str, list] = {}
    for m in analysis.metrics.values():
        sections.setdefault(m.section, []).append(m)
    for section, metrics in sections.items():
        st.markdown(f"**{section}**")
        _table([(m.label, format_value(m.value, m.unit, cur), m.formula,
                 "Calculated · uses assumptions" if m.depends_on_assumptions else "Calculated")
                for m in metrics], ["Metric", "Value", "Formula", "Tag"])
        for m in metrics:
            if m.note:
                st.caption(md(f"↳ {m.label}: {m.note}"))

    _render_sources(deal, analysis, sources)


def _render_sources(deal: DealInputs, analysis: TransactionAnalysis, sources: dict) -> None:
    st.subheader("Sources")
    if not sources["sources"]:
        st.info("No sources recorded for this deal.")
        return

    st.markdown("**Documents**")
    for key, text in sources["documents"].items():
        st.markdown(f"- **{key}**: " + URL.sub(lambda u: f"[{u.group()}]({u.group()})", md(text)))

    st.markdown("**Figures**")
    figures = sources["sources"]
    _table([(field, _display(_lookup(deal, field)), s.get("document", "—"), s.get("page", "—"),
             s.get("as_of", "—")) for field, s in figures.items()],
           ["Field", "Value", "Document", "Page", "As of"])
    field = st.selectbox("Figure detail", list(figures))
    detail = figures[field]
    for label, key in (("Section", "section"), ("Snippet", "snippet"), ("Note", "note")):
        if detail.get(key):
            text = f"> {md(detail[key])}" if key == "snippet" else md(detail[key])
            st.markdown(f"**{label}**" + ("\n\n" if key == "snippet" else ": ") + text)

    if sources["cross_checks"]:
        st.markdown("**Cross-checks**")
        rows, notes = [], []
        for name, c in sources["cross_checks"].items():
            ours = analysis.metrics.get(c.get("compare_to", ""))
            unit = ours.unit if ours else ""
            rows.append((name, format_value(c.get("value"), unit, deal.info.currency),
                         f"{ours.label}: {format_value(ours.value, unit, deal.info.currency)}" if ours else "",
                         c.get("document", ""), c.get("page", "")))
            notes.append(f"↳ {name}: \"{c.get('snippet', '')}\" {c.get('note', '')}")
        _table(rows, ["Check", "Published", "Our figure", "Document", "Page"])
        for note in notes:
            st.caption(md(note))

    for path in {m for text in sources["documents"].values() for m in EVIDENCE_FILE.findall(text)}:
        with st.expander(f"Evidence: {path}"):
            if (PROJECT_ROOT / path).exists():
                st.image(str(PROJECT_ROOT / path))
            else:
                st.caption("File not found.")


def _lookup(deal: DealInputs, field: str):
    """Input value for a _sources key such as 'cash' or 'share_build.option_tranches[0].strike'."""
    first = field.split(".")[0]
    obj = deal.facts if hasattr(deal.facts, first) else deal.assumptions
    for part in re.findall(r"\w+|\[\d+\]", field):
        if obj is None:
            return None
        obj = obj[int(part[1:-1])] if part.startswith("[") else getattr(obj, part, None)
    return obj


def _display(value) -> str:
    return "—" if value is None else f"{value:,}" if isinstance(value, (int, float)) else str(value)


def _table(rows: list[tuple], columns: list[str]) -> None:
    st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True, column_config={
        c: st.column_config.TextColumn(width=w) for c, w in COLUMN_WIDTHS.items() if c in columns})
