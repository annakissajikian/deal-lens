"""Display helpers: 13.60x, 20.0%, $6,000m, 106.00m shares, n.m."""

from __future__ import annotations

from typing import Optional

SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€", "BRL": "R$"}


def format_value(value: Optional[float], unit: str, currency: str = "USD") -> str:
    if value is None:
        return "n.m."
    symbol = SYMBOLS.get(currency, currency + " ")
    if unit == "currency":
        return f"{symbol}{value:,.0f}m" if value >= 0 else f"({symbol}{abs(value):,.0f}m)"
    if unit == "multiple":
        return f"{value:.2f}x"
    if unit == "percent":
        return f"{value:.1%}"
    if unit == "shares":
        return f"{value:,.2f}m"
    return f"{value:,.2f}"
