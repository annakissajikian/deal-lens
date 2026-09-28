"""
Transaction analysis engine (Step 1).

Deterministic: the same inputs always give the same outputs. No AI is used.
The small functions hold one formula each so they can be read and tested on
their own; analyse_transaction() applies them all to a deal.
"""

from __future__ import annotations

from typing import Optional

from .dilution import diluted_share_count, treasury_stock_method
from .models import DealInputs, Metric, TransactionAnalysis
from .validation import validate


# ---------------------------------------------------------------- helpers --

def multiple(numerator: float, denominator: Optional[float]) -> Optional[float]:
    """Valuation multiple; None (n.m.) if the denominator is missing, zero or negative."""
    if denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def ratio(numerator: Optional[float], denominator: float) -> Optional[float]:
    """Plain ratio such as a margin; None only if an input is missing or the denominator is zero."""
    if numerator is None or denominator == 0:
        return None
    return numerator / denominator


# --------------------------------------------------------------- formulas --

def equity_value(price_per_share: float, diluted_shares: float) -> float:
    return price_per_share * diluted_shares


def enterprise_value(equity: float, debt: float, cash: float) -> float:
    return equity + debt - cash


def acquisition_premium(offer_price: float, unaffected_price: float) -> float:
    return offer_price / unaffected_price - 1


def revenue_synergy_margin(inputs: DealInputs) -> tuple[float, bool]:
    """Margin applied to synergy revenue, and whether it is the fallback."""
    a, f = inputs.assumptions, inputs.facts
    if a.revenue_synergy_incremental_margin is not None:
        return a.revenue_synergy_incremental_margin, False
    fallback = ratio(f.ebitda, f.revenue)
    return (max(fallback, 0.0) if fallback is not None else 0.0), True


# ---------------------------------------------------------------- analysis --

def analyse_transaction(inputs: DealInputs) -> TransactionAnalysis:
    warnings = validate(inputs)                     # raises DealInputError if unusable
    result = TransactionAnalysis(inputs=inputs, warnings=warnings)
    f, a = inputs.facts, inputs.assumptions

    def add(key, label, value, unit, formula, section, assumption=False, note=""):
        if value is None and not note:
            note = "n.m.: denominator missing, zero or negative."
        result.metrics[key] = Metric(key, label, value, unit, formula, section, assumption, note)

    # Share count (only shown when calculated from a share build)
    shares = diluted_share_count(f)
    if f.share_build is not None:
        b, price = f.share_build, f.offer_price_per_share
        exercised, repurchased = treasury_stock_method(b.option_tranches, price)
        out_of_money = sum(t.number for t in b.option_tranches if t.strike >= price)
        add("basic_shares", "Basic shares outstanding", b.basic_shares, "shares",
            "Input (share build)", "Share count", note=f"As of: {b.as_of}" if b.as_of else "")
        add("options_exercised", "In-the-money options exercised", exercised, "shares",
            "Σ options with strike < Offer price", "Share count",
            note=f"{out_of_money:,.2f}m options with strike ≥ offer price excluded (out of the money)."
            if out_of_money else "")
        add("shares_repurchased", "Shares repurchased with exercise proceeds", repurchased, "shares",
            "Σ (Options × Strike) ÷ Offer price", "Share count")
        add("net_option_shares", "Net new shares from options", exercised - repurchased, "shares",
            "Options exercised − Shares repurchased", "Share count")
        add("rsus", "RSUs / PSUs", b.rsus, "shares", "Input (share build)", "Share count",
            note="Each unit counts as one share (no strike); PSUs at target.")
        add("fully_diluted_shares", "Fully diluted shares", shares, "shares",
            "Basic + Net new shares from options + RSUs/PSUs", "Share count",
            note="Treasury stock method at the offer price. The same count is used for the unaffected "
                 "equity value (simplification: at the lower unaffected price fewer options would be "
                 "in the money, giving slightly fewer shares).")

    # Transaction value
    eq = equity_value(f.offer_price_per_share, shares)
    net_debt = f.total_debt - f.cash
    ev = enterprise_value(eq, f.total_debt, f.cash)
    add("equity_value", "Transaction equity value", eq, "currency",
        "Offer price × Diluted shares outstanding", "Transaction value")
    add("net_debt", "Net debt", net_debt, "currency", "Debt − Cash", "Transaction value")
    add("enterprise_value", "Transaction enterprise value", ev, "currency",
        "Transaction equity value + Debt − Cash", "Transaction value")

    # Premium
    unaffected_eq = equity_value(f.unaffected_share_price, shares)
    add("premium", "Acquisition premium",
        acquisition_premium(f.offer_price_per_share, f.unaffected_share_price), "percent",
        "Offer price ÷ Unaffected share price − 1", "Premium")
    add("unaffected_equity_value", "Unaffected equity value", unaffected_eq, "currency",
        "Unaffected share price × Diluted shares", "Premium")
    add("premium_paid", "Premium paid", eq - unaffected_eq, "currency",
        "Transaction equity value − Unaffected equity value", "Premium")

    # Transaction multiples (at the offer price)
    add("ev_revenue", "EV / Revenue", multiple(ev, f.revenue), "multiple",
        "Transaction EV ÷ Revenue", "Transaction multiples")
    add("ev_ebitda", "EV / EBITDA", multiple(ev, f.ebitda), "multiple",
        "Transaction EV ÷ EBITDA", "Transaction multiples")
    add("ev_ebit", "EV / EBIT", multiple(ev, f.ebit), "multiple",
        "Transaction EV ÷ EBIT", "Transaction multiples",
        note="" if f.ebit is not None else "Unavailable: EBIT not provided.")
    add("pe", "Equity value / Net income", multiple(eq, f.net_income), "multiple",
        "Transaction equity value ÷ Net income", "Transaction multiples",
        note="" if f.net_income is not None else "Unavailable: net income not provided.")

    # Trading multiples (at the unaffected price, before the deal)
    unaffected_ev = enterprise_value(unaffected_eq, f.total_debt, f.cash)
    add("unaffected_ev", "Unaffected enterprise value", unaffected_ev, "currency",
        "Unaffected equity value + Debt − Cash", "Trading multiples (unaffected)")
    add("unaffected_ev_ebitda", "Unaffected EV / EBITDA", multiple(unaffected_ev, f.ebitda), "multiple",
        "Unaffected EV ÷ EBITDA", "Trading multiples (unaffected)")

    # Profitability
    add("ebitda_margin", "EBITDA margin", ratio(f.ebitda, f.revenue), "percent",
        "EBITDA ÷ Revenue", "Profitability")

    # Synergies (all depend on assumptions)
    margin, is_fallback = revenue_synergy_margin(inputs)
    rev_contrib = a.revenue_synergies * margin
    total_syn = a.cost_synergies + rev_contrib
    pro_forma_ebitda = f.ebitda + total_syn
    add("revenue_synergy_ebitda", "Revenue synergy EBITDA contribution", rev_contrib, "currency",
        "Revenue synergies × Incremental margin", "Synergies", assumption=True,
        note="ASSUMPTION: target EBITDA margin used as incremental margin." if is_fallback and a.revenue_synergies else "")
    add("total_synergy_ebitda", "Total run-rate synergy EBITDA", total_syn, "currency",
        "Cost synergies + Revenue synergy EBITDA contribution", "Synergies", assumption=True)
    add("pro_forma_ebitda", "Pro forma EBITDA", pro_forma_ebitda, "currency",
        "Target EBITDA + Cost synergies + Revenue synergy EBITDA contribution", "Synergies", assumption=True)
    add("synergy_adj_ev_ebitda", "Synergy-adjusted EV / EBITDA", multiple(ev, pro_forma_ebitda), "multiple",
        "Transaction EV ÷ Pro forma EBITDA", "Synergies", assumption=True)
    add("after_tax_synergies", "Illustrative after-tax synergy contribution",
        total_syn * (1 - a.tax_rate) if a.tax_rate is not None else None, "currency",
        "Total run-rate synergy EBITDA × (1 − Tax rate)", "Synergies", assumption=True,
        note=("Simplified illustrative figure only: not synergy cash flow, synergy NPV or a full "
              "synergy valuation (ignores integration costs, phasing, CapEx and working capital)."
              if a.tax_rate is not None else "Unavailable: tax rate not provided."))

    # Financing (split of consideration only, not pro forma leverage)
    for source, share in (("cash", a.financing_cash), ("debt", a.financing_debt), ("stock", a.financing_stock)):
        add(f"financed_{source}", f"Financed with {source}", eq * share, "currency",
            f"Transaction equity value × {source.capitalize()} share", "Financing", assumption=True)

    return result
