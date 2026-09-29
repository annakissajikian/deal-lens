"""
Load a deal from JSON into DealInputs.

The JSON has three sections that mirror the data model:
    "deal"         -> DealInfo
    "facts"        -> DealFacts
    "assumptions"  -> DealAssumptions
Keys starting with "_" are treated as comments and ignored.

"facts" may contain an optional "share_build" object (basic_shares, rsus,
as_of and a list of option_tranches, each {number, strike}).

An optional "dcf" section holds the DCF inputs (forecast_years, unlevered_fcf,
wacc, terminal_growth, valuation_date, wacc_range, growth_range).

An optional "valuation" section holds "multiples" (trading comps / precedent
transactions, each with name, method, metric_label, metric_value, optional
peers [{name, multiple}], multiple_low, multiple_high) and "references"
(per-share ranges [{name, low, high}]).

Every structural problem (wrong types, missing sections, bad dates) is raised
as a DealInputError, never as a raw Python error.

Real-deal files may also carry "_documents", "_sources" and "_cross_checks".
load_deal() ignores them (they are provenance, not inputs); load_sources()
returns them for display.

deal_from_dict() does the parsing for both a JSON file (load_deal) and the
app's input form, so every deal goes through exactly the same checks.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import date
from pathlib import Path

from finance.models import (DCFInputs, DealAssumptions, DealFacts, DealInfo, DealInputError, DealInputs,
                            MultipleValuation, OptionTranche, Peer, ReferenceRange, ShareBuild,
                            ValuationInputs)

SECTIONS = {"deal": DealInfo, "facts": DealFacts, "assumptions": DealAssumptions}
SAMPLE_DEALS_DIR = Path(__file__).parent.parent / "data" / "sample_deals"
USER_DEALS_DIR = Path(__file__).parent.parent / "data" / "user_deals"
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
    return deal_from_dict(raw)


def deal_from_dict(raw) -> DealInputs:
    """Parse a deal in JSON form (a dict with "deal", "facts", "assumptions") into DealInputs."""
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
        dcf=_parse_dcf(raw["dcf"]) if raw.get("dcf") is not None else None,
        valuation=_parse_valuation(raw["valuation"]) if raw.get("valuation") is not None else None,
    )


def _objects(section: str, raw) -> list[dict]:
    """A list of JSON objects, or a DealInputError naming what is wrong."""
    if not isinstance(raw, list):
        raise DealInputError([f"{section} must be a list [...], got {type(raw).__name__}."])
    bad = [f"{section}[{i}] must be an object {{...}}." for i, x in enumerate(raw) if not isinstance(x, dict)]
    if bad:
        raise DealInputError(bad)
    return raw


def _parse_valuation(raw) -> ValuationInputs:
    if not isinstance(raw, dict):
        raise DealInputError([f"Section 'valuation' must be an object {{...}}, got {type(raw).__name__}."])
    unknown = [k for k in raw if k not in ("multiples", "references") and not k.startswith("_")]
    if unknown:
        raise DealInputError([f"Unknown field in 'valuation': '{k}'" for k in unknown])
    multiples = []
    for i, m in enumerate(_objects("valuation.multiples", raw.get("multiples", []))):
        data = dict(m)
        data["peers"] = tuple(_build(f"valuation.multiples[{i}].peers[{j}]", Peer, p) for j, p in
                              enumerate(_objects(f"valuation.multiples[{i}].peers", data.get("peers", []))))
        multiples.append(_build(f"valuation.multiples[{i}]", MultipleValuation, data))
    references = tuple(_build(f"valuation.references[{i}]", ReferenceRange, r)
                       for i, r in enumerate(_objects("valuation.references", raw.get("references", []))))
    return ValuationInputs(multiples=tuple(multiples), references=references)


def _parse_dcf(raw) -> DCFInputs:
    if not isinstance(raw, dict):
        raise DealInputError([f"Section 'dcf' must be an object {{...}}, got {type(raw).__name__}."])
    data = dict(raw)
    for key in ("forecast_years", "unlevered_fcf", "wacc_range", "growth_range"):
        if key in data:
            if not isinstance(data[key], list):
                raise DealInputError([f"dcf.{key} must be a list [...], got {type(data[key]).__name__}."])
            data[key] = tuple(data[key])
    return _build("dcf", DCFInputs, data)


def list_sample_deals(folder: str | Path | None = None) -> dict[str, Path]:
    """Map an 'Acquirer / Target' label to each deal file in `folder` (default data/sample_deals/)."""
    deals: dict[str, Path] = {}
    for path in sorted(Path(folder or SAMPLE_DEALS_DIR).glob("*.json")):
        try:
            info = json.loads(path.read_text(encoding="utf-8"))["deal"]
            label = f"{info['acquirer']} / {info['target']}"
        except (json.JSONDecodeError, KeyError, TypeError):
            label = path.stem   # still listed: loading it shows the validation errors
        deals[label] = path
    return deals


def load_sources(path: str | Path) -> dict[str, dict]:
    """The provenance blocks of a deal file; empty dicts when a file has none."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raw = {}
    return {key: raw.get(f"_{key}", {}) for key in ("documents", "sources", "cross_checks")}


def deal_filename(raw: dict) -> str:
    """Safe file name from the deal's names, e.g. 'Northwind Holdings' + 'Apex' -> 'northwind_holdings_apex.json'."""
    info = raw.get("deal", {})
    name = f"{info.get('acquirer', '')} {info.get('target', '')}".lower()
    return (re.sub(r"[^a-z0-9]+", "_", name).strip("_") or "deal") + ".json"


def save_deal(raw: dict, folder: str | Path | None = None, overwrite: bool = False) -> Path:
    """Write a deal dict as JSON to `folder` (default data/user_deals/). Refuses to overwrite unless asked."""
    folder = Path(folder or USER_DEALS_DIR)
    path = folder / deal_filename(raw)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path.name} already exists in {folder.name}/.")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
