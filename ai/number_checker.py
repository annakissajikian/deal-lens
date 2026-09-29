"""
Number checker (Step 6): every figure in the AI's text must come from the engine.

The allowed set is every number that appears anywhere in the payload (values as
displayed, labels such as "CY2022E", dates, formulas). The model is told to copy
figures exactly as displayed, so a rounded, converted ("$68.8bn") or invented
number is not in the set and the statement is rejected.

Signs are ignored ("-4.1%" and "4.1%" are the same figure), as are thousands
separators and trailing zeros ("95" = "95.00").
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

# A number: digits with optional thousands separators and decimals ("68,824", "20.39", "2022")
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def numbers_in(text: str) -> list[str]:
    """Every number written in `text`, as it appears (e.g. ['68,824', '20.39'])."""
    return NUMBER.findall(text)


def _normal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def allowed_numbers(payload: dict) -> set[Decimal]:
    """Every number that appears anywhere in the payload."""
    text = json.dumps(payload, ensure_ascii=False)
    return {n for n in (_normal(t) for t in numbers_in(text)) if n is not None}


def unsupported_numbers(text: str, allowed: set[Decimal]) -> list[str]:
    """Numbers in `text` that the engine did not produce (empty list = the text passes)."""
    return [t for t in numbers_in(text) if _normal(t) not in allowed]
