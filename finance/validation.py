"""
Input validation.

ERROR   -> the analysis cannot proceed. All errors are collected and raised together.
WARNING -> the analysis runs, but a person should review the data or assumption.
"""

from __future__ import annotations

import math
from dataclasses import fields
from datetime import date
from numbers import Real

from .models import DealAssumptions, DealFacts, DealInputError, DealInputs

FINANCING_TOLERANCE = 0.001        # financing mix must total 100% +/- 0.1%
EQUITY_VALUE_TOLERANCE = 0.02      # stated vs calculated equity value: 2%
LARGE_PREMIUM_THRESHOLD = 0.50     # premiums above this are flagged for review

# Numeric inputs that must always be present (None / JSON null is rejected).
# The assumption fields have defaults, but an explicit null is still an error.
REQUIRED_NUMERIC = ("offer_price_per_share", "unaffected_share_price", "diluted_shares_outstanding",
                    "revenue", "ebitda", "total_debt", "cash",
                    "cost_synergies", "revenue_synergies",
                    "financing_cash", "financing_debt", "financing_stock")
# Numeric inputs that may be None (= not provided).
OPTIONAL_NUMERIC = ("net_income", "ebit", "stated_equity_value",
                    "revenue_synergy_incremental_margin", "tax_rate")

MUST_BE_POSITIVE = ("offer_price_per_share", "unaffected_share_price", "diluted_shares_outstanding")
MUST_NOT_BE_NEGATIVE = ("revenue", "total_debt", "cash", "cost_synergies", "revenue_synergies")
PERCENTAGES = ("revenue_synergy_incremental_margin", "financing_cash", "financing_debt",
               "financing_stock", "tax_rate")
OPTIONAL_FACTS = ("net_income", "ebit", "stated_equity_value")


def _is_number(x) -> bool:
    """True for real, finite numbers. Rejects bools, text, None, NaN and +/-infinity."""
    return isinstance(x, Real) and not isinstance(x, bool) and math.isfinite(x)


def validate(inputs: DealInputs) -> list[str]:
    """Raise DealInputError if inputs are unusable; otherwise return warnings."""
    errors: list[str] = []
    f, a = inputs.facts, inputs.assumptions

    # 1. Names and date
    for name in ("acquirer", "target"):
        v = getattr(inputs.info, name)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"{name} must be non-empty text.")
    d = inputs.info.announcement_date
    if d is not None and not isinstance(d, date):
        errors.append(f"announcement_date must be a date in YYYY-MM-DD format (got {d!r}).")

    # 2. Presence and type: required numbers must exist; all numbers must be finite
    values = {fl.name: getattr(f, fl.name) for fl in fields(DealFacts)}
    values.update({fl.name: getattr(a, fl.name) for fl in fields(DealAssumptions)})
    for name in REQUIRED_NUMERIC:
        v = values[name]
        if v is None:
            errors.append(f"{name} is required and cannot be null/None.")
        elif not _is_number(v):
            errors.append(f"{name} must be a finite number (got {v!r}).")
    for name in OPTIONAL_NUMERIC:
        v = values[name]
        if v is not None and not _is_number(v):
            errors.append(f"{name} must be a finite number or null (got {v!r}).")
    if errors:                       # range checks need valid numbers
        raise DealInputError(errors)

    # 3. Ranges
    for name in MUST_BE_POSITIVE:
        if values[name] <= 0:
            errors.append(f"{name} must be greater than zero.")
    for name in MUST_NOT_BE_NEGATIVE:
        if values[name] < 0:
            errors.append(f"{name} cannot be negative.")
    for name in PERCENTAGES:
        v = values[name]
        if v is not None and not 0 <= v <= 1:
            errors.append(f"{name} must be a decimal between 0 and 1 (e.g. 0.30 for 30%), got {v}.")
    if f.stated_equity_value is not None and f.stated_equity_value <= 0:
        errors.append("stated_equity_value must be greater than zero if provided.")

    mix_total = a.financing_cash + a.financing_debt + a.financing_stock
    if abs(mix_total - 1) > FINANCING_TOLERANCE:
        errors.append(f"Financing mix must total 100% (currently {mix_total:.1%}).")

    if errors:
        raise DealInputError(errors)

    return _warnings(inputs)


def _warnings(inputs: DealInputs) -> list[str]:
    f, a = inputs.facts, inputs.assumptions
    w: list[str] = []

    # Equity value cross-check
    if f.stated_equity_value is not None:
        calculated = f.offer_price_per_share * f.diluted_shares_outstanding
        gap = f.stated_equity_value / calculated - 1
        if abs(gap) > EQUITY_VALUE_TOLERANCE:
            w.append(f"Stated equity value ({f.stated_equity_value:,.0f}) differs from offer price x "
                     f"diluted shares ({calculated:,.0f}) by {gap:+.1%}. The calculated figure is used; "
                     f"check the share count (basic vs fully diluted).")

    # Premium
    prem = f.offer_price_per_share / f.unaffected_share_price - 1
    if prem < 0:
        w.append("Offer price is below the unaffected share price (negative premium). "
                 "Check the unaffected price date.")
    elif prem > LARGE_PREMIUM_THRESHOLD:
        w.append(f"Acquisition premium ({prem:.1%}) exceeds the configured "
                 f"{LARGE_PREMIUM_THRESHOLD:.0%} review threshold. Check the unaffected share "
                 f"price and transaction terms.")

    # Synergy margin fallback
    if a.revenue_synergies > 0 and a.revenue_synergy_incremental_margin is None:
        if f.ebitda > 0 and f.revenue > 0:
            w.append(f"revenue_synergy_incremental_margin not provided: ASSUMING the target EBITDA "
                     f"margin ({f.ebitda / f.revenue:.1%}) applies to synergy revenue.")
        else:
            w.append("revenue_synergy_incremental_margin not provided and target EBITDA margin is not "
                     "positive: revenue synergies are treated as contributing zero EBITDA.")

    # Data sanity
    if f.ebitda <= 0:
        w.append("EBITDA is zero or negative: EBITDA-based multiples are not meaningful.")
    if f.ebitda > f.revenue > 0:
        w.append("EBITDA exceeds revenue. Check units (all amounts should be in millions).")
    if f.ebit is not None and f.ebit > f.ebitda:
        w.append("EBIT exceeds EBITDA, implying negative D&A. Check the inputs.")

    # Missing optional inputs
    for name in OPTIONAL_FACTS:
        if getattr(f, name) is None:
            w.append(f"Optional fact '{name}' not provided; related metrics are unavailable.")
    if a.tax_rate is None:
        w.append("Optional assumption 'tax_rate' not provided; after-tax synergies are unavailable.")
    if inputs.info.announcement_date is None:
        w.append("Announcement date not provided.")

    return w
