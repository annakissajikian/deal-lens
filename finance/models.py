"""
Data structures for DealLens.

The inputs are split into three groups so that every number carries its
provenance:

    DealInfo         descriptive labels (names, sector, date, currency)
    DealFacts        observable data: deal terms and reported financials
    DealAssumptions  user judgements: synergies, margins, financing, tax

The engine's outputs are Metric objects. Each Metric stores its value, the
formula used, and whether it depends on any assumption. The future AI
analyst will receive this structure, so it can always tell a reported fact
from an assumption or a calculated number.

Conventions used everywhere:
  * Money in millions of `currency` (6,000 = 6bn).
  * Shares in millions. Prices per share.
  * Percentages as decimals (0.20 = 20%).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from typing import Optional


class DealInputError(ValueError):
    """Raised when inputs cannot be analysed. Holds every problem found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Invalid deal inputs:\n  - " + "\n  - ".join(errors))


@dataclass(frozen=True)
class DealInfo:
    acquirer: str
    target: str
    sector: str
    announcement_date: Optional[date] = None
    currency: str = "USD"


@dataclass(frozen=True)
class OptionTranche:
    """One exercise-price range from the stock option table in the 10-K."""
    number: float                           # millions of options outstanding
    strike: float                           # weighted-average exercise price per share


@dataclass(frozen=True)
class ShareBuild:
    """Components of the fully diluted share count (treasury stock method)."""
    basic_shares: float                     # millions, shares actually outstanding
    option_tranches: tuple[OptionTranche, ...] = ()
    rsus: float = 0.0                       # millions of unvested RSUs + PSUs (PSUs at target)
    as_of: str = ""                         # dates of the counts, e.g. "basic 2022-02-15; awards 2021-12-31"


@dataclass(frozen=True)
class DealFacts:
    # Deal terms
    offer_price_per_share: float
    unaffected_share_price: float           # pre-announcement, undisturbed price
    # Target financials (all for the same period)
    revenue: float
    ebitda: float
    total_debt: float
    cash: float
    net_income: Optional[float] = None
    ebit: Optional[float] = None
    stated_equity_value: Optional[float] = None   # headline figure, used only as a cross-check
    financials_period: str = "LTM"
    # Share count (millions): enter the fully diluted figure directly OR give a
    # share_build and the engine calculates it with the treasury stock method.
    diluted_shares_outstanding: Optional[float] = None
    share_build: Optional[ShareBuild] = None


@dataclass(frozen=True)
class DealAssumptions:
    cost_synergies: float = 0.0                              # annual run-rate, pre-tax
    revenue_synergies: float = 0.0                           # annual run-rate revenue
    revenue_synergy_incremental_margin: Optional[float] = None
    financing_cash: float = 1.0                              # share of consideration
    financing_debt: float = 0.0
    financing_stock: float = 0.0
    tax_rate: Optional[float] = None


@dataclass(frozen=True)
class DealInputs:
    info: DealInfo
    facts: DealFacts
    assumptions: DealAssumptions

    def provenance(self) -> dict[str, str]:
        """Map every input field to 'fact' or 'assumption'."""
        tags = {f.name: "fact" for f in fields(DealFacts)}
        tags.update({f.name: "assumption" for f in fields(DealAssumptions)})
        return tags


@dataclass(frozen=True)
class Metric:
    key: str                      # machine name, e.g. "ev_ebitda"
    label: str                    # display name, e.g. "EV / EBITDA"
    value: Optional[float]        # None = not meaningful (see note)
    unit: str                     # "currency" | "multiple" | "percent" | "shares"
    formula: str
    section: str
    depends_on_assumptions: bool = False
    note: str = ""


@dataclass
class TransactionAnalysis:
    inputs: DealInputs
    metrics: dict[str, Metric] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def value(self, key: str) -> Optional[float]:
        return self.metrics[key].value
