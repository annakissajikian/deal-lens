"""Display helpers: 13.60x, 20.0%, $6,000m, $95.00 per share, 106.00m shares, n.m."""

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
    if unit == "percent_2":                 # rates such as WACC 7.25%
        return f"{value:.2%}"
    if unit == "per_share":
        return f"{symbol}{value:,.2f}"
    if unit == "shares":
        return f"{value:,.2f}m"
    return f"{value:,.2f}"


def md(text: str) -> str:
    """Escape '$' so Streamlit markdown shows it as text, not as the start of a maths formula."""
    return text.replace("$", "\\$")
