"""
Fully diluted shares with the treasury stock method (Step 2).

A buyer pays for every share that will exist at closing. Options whose strike
is below the offer price are assumed to be exercised; the company is assumed
to use the exercise cash to buy back shares at the offer price. Only the net
new shares add to the count. RSUs/PSUs have no strike, so each counts in full.

    Options exercised    = options with strike < price
    Shares repurchased   = Σ (options × strike) ÷ price
    Fully diluted shares = Basic + Options exercised − Shares repurchased + RSUs

The method is applied tranche by tranche: one weighted-average strike can hide
options that are out of the money and so misstate the dilution.
"""

from __future__ import annotations

from .models import DealFacts, OptionTranche, ShareBuild


def treasury_stock_method(tranches: tuple[OptionTranche, ...], price: float) -> tuple[float, float]:
    """(Options exercised, Shares repurchased) for the in-the-money tranches at `price`."""
    in_the_money = [t for t in tranches if t.strike < price]
    exercised = sum(t.number for t in in_the_money)
    repurchased = sum(t.number * t.strike for t in in_the_money) / price
    return exercised, repurchased


def fully_diluted_shares(build: ShareBuild, price: float) -> float:
    exercised, repurchased = treasury_stock_method(build.option_tranches, price)
    return build.basic_shares + exercised - repurchased + build.rsus


def diluted_share_count(facts: DealFacts) -> float:
    """The share count the engine uses: the share build at the offer price if given, else the entered figure."""
    if facts.share_build is None:
        return facts.diluted_shares_outstanding
    return fully_diluted_shares(facts.share_build, facts.offer_price_per_share)
