"""
Build the structured payload the AI analyst receives (Step 6).

The payload is the ONLY data the model sees. Every item carries:
    id           stable key the model must cite
    label        human name
    display      the value exactly as DealLens shows it (the model must copy it verbatim)
    provenance   fact | assumption | calculated | calculated_from_assumptions
    source/note  where it came from, when known

Missing data is listed under "unavailable" so the model says so instead of guessing.
"""

from __future__ import annotations

from typing import Optional

from finance.comps import ValuationAnalysis
from finance.dcf import DCFAnalysis
from finance.models import TransactionAnalysis
from utils.formatting import format_value

PROVENANCES = ("fact", "assumption", "calculated", "calculated_from_assumptions")

INPUT_UNITS = {
    "offer_price_per_share": "per_share", "unaffected_share_price": "per_share",
    "revenue": "currency", "ebitda": "currency", "ebit": "currency", "net_income": "currency",
    "total_debt": "currency", "cash": "currency", "stated_equity_value": "currency",
    "cost_synergies": "currency", "revenue_synergies": "currency",
    "revenue_synergy_incremental_margin": "percent", "financing_cash": "percent",
    "financing_debt": "percent", "financing_stock": "percent", "tax_rate": "percent",
}


def build_payload(analysis: TransactionAnalysis, sources: dict, dcf: Optional[DCFAnalysis] = None,
                  valuation: Optional[ValuationAnalysis] = None) -> dict:
    deal, cur = analysis.inputs, analysis.inputs.info.currency
    notes = sources.get("sources", {})
    items: list[dict] = []
    unavailable: list[str] = []

    def add(item_id, label, value, unit, provenance, formula="", source=""):
        items.append({"id": item_id, "label": label, "display": format_value(value, unit, cur),
                      "provenance": provenance, "formula": formula, "source": source})

    def source_of(field):
        s = notes.get(field, {})
        where = " ".join(x for x in (s.get("document", ""), s.get("page", "")) if x)
        return "; ".join(x for x in (where, s.get("note", "")) if x)

    provenance = deal.provenance()
    for field, unit in INPUT_UNITS.items():
        obj = deal.facts if hasattr(deal.facts, field) else deal.assumptions
        value = getattr(obj, field)
        if value is None:
            reason = notes.get(field, {}).get("note", "not provided")
            unavailable.append(f"{field}: {reason}")
            continue
        add(field, field.replace("_", " "), value, unit, provenance[field], source=source_of(field))

    for m in analysis.metrics.values():
        if m.value is None:
            unavailable.append(f"{m.key}: {m.note or 'not meaningful'}")
            continue
        add(m.key, m.label, m.value, m.unit,
            "calculated_from_assumptions" if m.depends_on_assumptions else "calculated", m.formula)

    if dcf is None:
        unavailable.append("DCF: no forecast, WACC or terminal growth provided")
    else:
        d = deal.dcf
        add("dcf_wacc", "DCF WACC", d.wacc, "percent_2", "assumption", source=source_of("dcf.wacc"))
        add("dcf_terminal_growth", "DCF terminal growth", d.terminal_growth, "percent_2", "assumption",
            source=source_of("dcf.terminal_growth"))
        for m in dcf.metrics.values():
            if m.value is not None:
                add(m.key, m.label, m.value, m.unit, "calculated_from_assumptions", m.formula)
        low, high = dcf.grid_range()
        if low is not None:
            add("dcf_range_low", "DCF sensitivity range, low", low, "per_share", "calculated_from_assumptions")
            add("dcf_range_high", "DCF sensitivity range, high", high, "per_share", "calculated_from_assumptions")

    if valuation is None or not valuation.multiples:
        unavailable.append("Trading comps / precedent transactions: not provided")
    if valuation is not None:
        for i, m in enumerate(valuation.multiples):
            add(f"multiple_{i}_low", f"{m.source.name}: value per share, low", m.per_share_low, "per_share",
                "calculated_from_assumptions", "Low multiple × metric, less net debt, ÷ shares")
            add(f"multiple_{i}_high", f"{m.source.name}: value per share, high", m.per_share_high, "per_share",
                "calculated_from_assumptions", "High multiple × metric, less net debt, ÷ shares")
            if m.offer_multiple is not None:
                add(f"multiple_{i}_offer", f"{m.source.name}: offer multiple", m.offer_multiple, "multiple",
                    "calculated", f"Transaction EV ÷ {m.source.metric_label}")
        for i, b in enumerate(b for b in valuation.bars if b.category == "Market reference"):
            add(f"reference_{i}_low", f"{b.label}, low", b.low, "per_share", "fact")
            add(f"reference_{i}_high", f"{b.label}, high", b.high, "per_share", "fact")

    return {
        "deal": {"acquirer": deal.info.acquirer, "target": deal.info.target, "sector": deal.info.sector,
                 "announcement_date": deal.info.announcement_date.isoformat() if deal.info.announcement_date
                 else "unavailable", "currency": cur, "units": "millions; prices per share",
                 "financials_period": deal.facts.financials_period},
        "items": items,
        "warnings": list(analysis.warnings) + (list(dcf.warnings) if dcf else []),
        "unavailable": unavailable,
    }
