"""
Discounted cash flow valuation (Step 4).

Deterministic: the same inputs always give the same outputs. No AI is used.

    PV of each forecast cash flow = FCF_t ÷ (1 + WACC)^t          t = 1 … N (end of year)
    Terminal value (Gordon growth) = FCF_N × (1 + g) ÷ (WACC − g)
    PV of terminal value           = TV ÷ (1 + WACC)^N
    DCF enterprise value           = Σ PV of forecast FCF + PV of terminal value
    DCF equity value               = DCF EV − (Debt − Cash)
    DCF value per share            = DCF equity value ÷ Fully diluted shares

All DCF outputs depend on assumptions (the forecast, WACC and g), so every
metric is flagged depends_on_assumptions=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .dilution import diluted_share_count
from .models import DCFInputs, DealInputs, Metric

HIGH_TERMINAL_GROWTH = 0.04      # above typical long-run nominal GDP growth
HIGH_TV_SHARE = 0.75             # terminal value share of EV that dominates the valuation
WACC_REVIEW_RANGE = (0.05, 0.20)


# --------------------------------------------------------------- formulas --

def discount_factor(rate: float, t: float) -> float:
    return 1 / (1 + rate) ** t


def present_values(cash_flows: tuple[float, ...], rate: float) -> list[float]:
    """PV of each cash flow, discounted at the end of years 1 … N."""
    return [cf * discount_factor(rate, t) for t, cf in enumerate(cash_flows, start=1)]


def terminal_value(final_fcf: float, rate: float, growth: float) -> Optional[float]:
    """Gordon growth terminal value at the end of year N; None (n.m.) if rate ≤ g or final FCF ≤ 0."""
    if rate <= growth or final_fcf <= 0:
        return None
    return final_fcf * (1 + growth) / (rate - growth)


def dcf_enterprise_value(cash_flows: tuple[float, ...], rate: float, growth: float) -> Optional[float]:
    tv = terminal_value(cash_flows[-1], rate, growth)
    if tv is None:
        return None
    return sum(present_values(cash_flows, rate)) + tv * discount_factor(rate, len(cash_flows))


def value_per_share(enterprise_value: Optional[float], net_debt: float, shares: float) -> Optional[float]:
    return None if enterprise_value is None else (enterprise_value - net_debt) / shares


def default_axis(centre: float, step: float, points_each_side: int) -> tuple[float, ...]:
    return tuple(round(centre + step * i, 6) for i in range(-points_each_side, points_each_side + 1))


# ---------------------------------------------------------------- analysis --

@dataclass
class DCFAnalysis:
    metrics: dict[str, Metric] = field(default_factory=dict)
    schedule: list[dict] = field(default_factory=list)        # one row per forecast year
    wacc_axis: tuple[float, ...] = ()
    growth_axis: tuple[float, ...] = ()
    grid: list[list[Optional[float]]] = field(default_factory=list)   # value per share [wacc][growth]
    grid_offer_vs: list[list[Optional[float]]] = field(default_factory=list)   # offer ÷ cell value − 1
    warnings: list[str] = field(default_factory=list)

    def value(self, key: str) -> Optional[float]:
        return self.metrics[key].value

    def grid_range(self) -> tuple[Optional[float], Optional[float]]:
        """Lowest and highest value per share in the sensitivity grid (n.m. cells ignored)."""
        values = [v for row in self.grid for v in row if v is not None]
        return (min(values), max(values)) if values else (None, None)


def analyse_dcf(inputs: DealInputs) -> Optional[DCFAnalysis]:
    """DCF for a deal that has DCF inputs (validated with the deal); None if it has none."""
    d: Optional[DCFInputs] = inputs.dcf
    if d is None:
        return None
    f = inputs.facts
    shares, net_debt = diluted_share_count(f), f.total_debt - f.cash
    result = DCFAnalysis()

    def add(key, label, value, unit, formula, note=""):
        if value is None and not note:
            note = "n.m.: WACC must exceed terminal growth and the final-year FCF must be positive."
        result.metrics[key] = Metric(key, label, value, unit, formula, "DCF", True, note)

    pvs = present_values(d.unlevered_fcf, d.wacc)
    for t, (year, fcf, pv) in enumerate(zip(d.forecast_years, d.unlevered_fcf, pvs), start=1):
        result.schedule.append({"year": year, "period": t, "fcf": fcf,
                                "discount_factor": discount_factor(d.wacc, t), "pv": pv})

    tv = terminal_value(d.unlevered_fcf[-1], d.wacc, d.terminal_growth)
    pv_tv = None if tv is None else tv * discount_factor(d.wacc, len(d.unlevered_fcf))
    ev = None if pv_tv is None else sum(pvs) + pv_tv
    equity = None if ev is None else ev - net_debt
    per_share = value_per_share(ev, net_debt, shares)

    add("pv_forecast_fcf", "PV of forecast cash flows", sum(pvs), "currency",
        "Σ FCF_t ÷ (1 + WACC)^t")
    add("terminal_value", "Terminal value (end of final year)", tv, "currency",
        "FCF_N × (1 + g) ÷ (WACC − g)")
    add("pv_terminal_value", "PV of terminal value", pv_tv, "currency", "Terminal value ÷ (1 + WACC)^N")
    add("dcf_enterprise_value", "DCF enterprise value", ev, "currency",
        "PV of forecast cash flows + PV of terminal value")
    add("dcf_equity_value", "DCF equity value", equity, "currency", "DCF enterprise value − (Debt − Cash)")
    add("dcf_value_per_share", "DCF value per share", per_share, "per_share",
        "DCF equity value ÷ Fully diluted shares",
        note="Uses the fully diluted share count at the offer price (simplification)."
        if per_share is not None else "")
    add("tv_share_of_ev", "Terminal value share of DCF EV", None if ev is None or ev <= 0 else pv_tv / ev,
        "percent", "PV of terminal value ÷ DCF enterprise value")
    add("offer_vs_dcf", "Offer price vs DCF value per share",
        None if per_share is None or per_share <= 0 else f.offer_price_per_share / per_share - 1, "percent",
        "Offer price ÷ DCF value per share − 1",
        note="Positive = the offer is above the DCF value; negative = below." if per_share else "")

    result.wacc_axis = d.wacc_range or default_axis(d.wacc, 0.005, 2)
    result.growth_axis = d.growth_range or default_axis(d.terminal_growth, 0.0025, 2)
    result.grid = [[value_per_share(dcf_enterprise_value(d.unlevered_fcf, w, g), net_debt, shares)
                    for g in result.growth_axis] for w in result.wacc_axis]
    result.grid_offer_vs = [[None if v is None or v <= 0 else f.offer_price_per_share / v - 1 for v in row]
                            for row in result.grid]
    result.warnings = dcf_warnings(d, result)
    return result


def dcf_warnings(d: DCFInputs, result: DCFAnalysis) -> list[str]:
    w: list[str] = []
    if d.unlevered_fcf[-1] <= 0:
        w.append("Final-year free cash flow is not positive: the terminal value is not meaningful.")
    if d.terminal_growth > HIGH_TERMINAL_GROWTH:
        w.append(f"Terminal growth ({d.terminal_growth:.2%}) is above {HIGH_TERMINAL_GROWTH:.0%}, higher than "
                 f"typical long-run nominal GDP growth. Check the assumption.")
    if not WACC_REVIEW_RANGE[0] <= d.wacc <= WACC_REVIEW_RANGE[1]:
        w.append(f"WACC ({d.wacc:.2%}) is outside the usual {WACC_REVIEW_RANGE[0]:.0%}–"
                 f"{WACC_REVIEW_RANGE[1]:.0%} range. Check the assumption.")
    share = result.value("tv_share_of_ev")
    if share is not None and share > HIGH_TV_SHARE:
        w.append(f"Terminal value is {share:.0%} of DCF enterprise value: the valuation depends mostly on "
                 f"the perpetuity assumptions (WACC and g).")
    return w
