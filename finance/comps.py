"""
Comparable companies, precedent transactions and the football field (Step 5).

Deterministic: the same inputs always give the same outputs. No AI is used.

For each multiple-based method:
    Selected range      = given low/high, or the peers' 25th-75th percentile
    Implied EV          = Selected multiple × Target metric
    Implied equity      = Implied EV − (Debt − Cash)
    Implied per share   = Implied equity ÷ Fully diluted shares
    Offer multiple      = Transaction EV ÷ Target metric   (what the buyer is paying)

The football field lines up every per-share range (DCF grid, comps,
precedents, market references) against the offer price.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional

from .dcf import DCFAnalysis
from .dilution import diluted_share_count
from .models import DealInputs, MultipleValuation
from .transaction import enterprise_value, equity_value, multiple


@dataclass
class MultipleResult:
    source: MultipleValuation
    peer_min: Optional[float]
    peer_median: Optional[float]
    peer_mean: Optional[float]
    peer_max: Optional[float]
    multiple_low: float
    multiple_high: float
    range_basis: str                          # "selected" or "interquartile range of peers"
    ev_low: float
    ev_high: float
    per_share_low: float
    per_share_high: float
    offer_multiple: Optional[float]


@dataclass
class FootballFieldBar:
    label: str
    category: str                             # "DCF", "Trading comps", "Precedent transactions", "Market reference"
    low: float                                # per share
    high: float


@dataclass
class ValuationAnalysis:
    multiples: list[MultipleResult] = field(default_factory=list)
    bars: list[FootballFieldBar] = field(default_factory=list)
    offer_price: float = 0.0
    unaffected_price: float = 0.0


# --------------------------------------------------------------- formulas --

def interquartile_range(values: list[float]) -> tuple[float, float]:
    """25th and 75th percentile (inclusive method: the ends are the min and max of the data)."""
    if len(values) == 1:
        return values[0], values[0]
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[2]


def implied_per_share(ev: float, net_debt: float, shares: float) -> float:
    return (ev - net_debt) / shares


# ---------------------------------------------------------------- analysis --

def analyse_valuation(inputs: DealInputs, dcf: Optional[DCFAnalysis] = None) -> Optional[ValuationAnalysis]:
    """Comps / precedents ranges and football field bars; None if the deal has no valuation inputs."""
    v = inputs.valuation
    if v is None and dcf is None:
        return None
    f = inputs.facts
    shares, net_debt = diluted_share_count(f), f.total_debt - f.cash
    transaction_ev = enterprise_value(equity_value(f.offer_price_per_share, shares), f.total_debt, f.cash)
    result = ValuationAnalysis(offer_price=f.offer_price_per_share, unaffected_price=f.unaffected_share_price)

    if dcf is not None:
        low, high = dcf.grid_range()
        if low is not None:
            result.bars.append(FootballFieldBar("DCF (WACC × growth sensitivity)", "DCF", low, high))

    for m in (v.multiples if v else ()):
        peers = [p.multiple for p in m.peers]
        if m.multiple_low is not None and m.multiple_high is not None:
            lo, hi, basis = m.multiple_low, m.multiple_high, "selected"
        else:
            lo, hi = interquartile_range(peers)
            basis = "interquartile range of peers"
        ev_lo, ev_hi = lo * m.metric_value, hi * m.metric_value
        r = MultipleResult(
            source=m,
            peer_min=min(peers) if peers else None, peer_median=statistics.median(peers) if peers else None,
            peer_mean=statistics.mean(peers) if peers else None, peer_max=max(peers) if peers else None,
            multiple_low=lo, multiple_high=hi, range_basis=basis, ev_low=ev_lo, ev_high=ev_hi,
            per_share_low=implied_per_share(ev_lo, net_debt, shares),
            per_share_high=implied_per_share(ev_hi, net_debt, shares),
            offer_multiple=multiple(transaction_ev, m.metric_value))
        result.multiples.append(r)
        category = "Trading comps" if m.method == "comps" else "Precedent transactions"
        result.bars.append(FootballFieldBar(m.name, category, r.per_share_low, r.per_share_high))

    for ref in (v.references if v else ()):
        result.bars.append(FootballFieldBar(ref.name, "Market reference", ref.low, ref.high))
    return result
