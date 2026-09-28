"""
Load a deal from JSON into DealInputs.

The JSON has three sections that mirror the data model:
    "deal"         -> DealInfo
    "facts"        -> DealFacts
    "assumptions"  -> DealAssumptions
Keys starting with "_" are treated as comments and ignored.

"facts" may contain an optional "share_build" object (basic_shares, rsus,
as_of and a list of option_tranches, each {number, strike}).

Every structural problem (wrong types, missing sections, bad dates) is raised
as a DealInputError, never as a raw Python error.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import date
from pathlib import Path

from finance.models import (DealAssumptions, DealFacts, DealInfo, DealInputError, DealInputs,
                            OptionTranche, ShareBuild)

SECTIONS = {"deal": DealInfo, "facts": DealFacts, "assumptions": DealAssumptions}
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def _build(section: str, cls, raw: dict):
    allowed = {f.name for f in fields(cls)}
    unknown = [k for k in raw if k not in allowed and not k.startswith("_")]
    if unknown:  # catches typos such as "ebidta" instead of ignoring them
        raise DealInputError([f"Unknown field in '{section}': '{k}'" for k in unknown])
    data = {k: v for k, v in raw.items() if k in allowed}
    try:
        return cls(**data)
    except TypeError as exc:  # a required field is missing
        raise DealInputError([f"Section '{section}': {exc}"]) from exc


def _parse_date(value) -> date:
    """Accept only text in YYYY-MM-DD form that is a real calendar date."""
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise DealInputError([f"announcement_date must be text in YYYY-MM-DD format (got {value!r})."])
    try:
        return date.fromisoformat(value)
    except ValueError as exc:  # e.g. 2026-02-30
        raise DealInputError([f"announcement_date must be a valid YYYY-MM-DD date: {exc}"]) from exc


def _parse_share_build(raw) -> ShareBuild:
    if not isinstance(raw, dict):
        raise DealInputError([f"share_build must be an object {{...}}, got {type(raw).__name__}."])
    data = dict(raw)
    tranches = data.get("option_tranches", [])
    if not isinstance(tranches, list):
        raise DealInputError([f"option_tranches must be a list [...], got {type(tranches).__name__}."])
    not_objects = [f"option_tranches[{i}] must be an object {{\"number\": ..., \"strike\": ...}}."
                   for i, t in enumerate(tranches) if not isinstance(t, dict)]
    if not_objects:
        raise DealInputError(not_objects)
    data["option_tranches"] = tuple(_build(f"option_tranches[{i}]", OptionTranche, t)
                                    for i, t in enumerate(tranches))
    return _build("share_build", ShareBuild, data)


def load_deal(path: str | Path) -> DealInputs:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DealInputError([f"{Path(path).name} is not valid JSON: {exc}"]) from exc

    if not isinstance(raw, dict):
        raise DealInputError([f"The JSON root must be an object {{...}}, got {type(raw).__name__}."])

    missing = [s for s in SECTIONS if s not in raw]
    if missing:
        raise DealInputError([f"Missing section: '{s}'" for s in missing])

    wrong_type = [s for s in SECTIONS if not isinstance(raw[s], dict)]
    if wrong_type:
        raise DealInputError([f"Section '{s}' must be an object {{...}}, got {type(raw[s]).__name__}."
                              for s in wrong_type])

    deal = dict(raw["deal"])
    if deal.get("announcement_date") is not None:
        deal["announcement_date"] = _parse_date(deal["announcement_date"])

    facts = dict(raw["facts"])
    if facts.get("share_build") is not None:
        facts["share_build"] = _parse_share_build(facts["share_build"])

    return DealInputs(
        info=_build("deal", DealInfo, deal),
        facts=_build("facts", DealFacts, facts),
        assumptions=_build("assumptions", DealAssumptions, raw["assumptions"]),
    )
