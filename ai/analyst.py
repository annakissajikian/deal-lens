"""
AI analyst (Step 6): Claude interprets the engine's outputs; it never calculates.

Flow:
  1. build_payload() -> the only data the model sees (ai/payload.py)
  2. ask_analyst()   -> one Claude API call with a structured output (AnalystReport)
  3. check_report()  -> every statement is verified before it is shown:
       * every number must appear in the payload (ai/number_checker.py)
       * cited item ids must exist
       * a "fact" statement may only cite facts, a "calculated" one only
         calculated items, an "assumption" one at least one assumption
     Statements that fail are removed and listed with the reason.

No API key -> the app says the AI analyst is unavailable; nothing else changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

from ai.number_checker import allowed_numbers, unsupported_numbers

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are a preliminary M&A analyst reviewing one transaction for a banking team.
You receive a JSON payload produced by a deterministic Python valuation engine. Your job is to
interpret it, not to compute anything.

Rules:
- Use only the payload. Every number you write must be copied exactly as it appears in an item's
  "display" value (same rounding, same units, e.g. "$68,824m", "20.39x", "45.3%"). Never calculate,
  round, convert (no "bn") or estimate a figure. If a figure you would need is not in the payload,
  do not write it: add what is missing to "unavailable" instead.
- Tag every statement with its kind:
    fact           restates a reported input (items with provenance "fact")
    assumption     restates or discusses a user or management assumption
    calculated     restates an engine output (provenance "calculated" or "calculated_from_assumptions")
    interpretation your own analytical judgement about what the figures mean
- In "item_ids" cite the ids of every payload item a statement relies on.
- Keep facts, assumptions, calculated figures and your interpretation distinguishable; say when a
  conclusion depends on assumptions (for example the DCF depends on WACC and terminal growth).
- Be concise and specific; write for an investment banking analyst. This is not investment advice.
"""


class Statement(BaseModel):
    text: str = Field(description="One sentence. Numbers copied exactly from payload display values.")
    kind: Literal["fact", "assumption", "calculated", "interpretation"]
    item_ids: list[str] = Field(description="Ids of the payload items this statement relies on.")


class AnalystReport(BaseModel):
    headline: Statement = Field(description="The single most important takeaway about the deal.")
    valuation: list[Statement] = Field(description="What the offer implies versus the valuation evidence.")
    premium_and_market: list[Statement] = Field(description="Premium and market reference points.")
    risks_and_limitations: list[Statement] = Field(description="Key risks, sensitivities and data limits.")
    unavailable: list[str] = Field(description="Data that would be needed but is not in the payload.")


SECTIONS = (("valuation", "Valuation"), ("premium_and_market", "Premium and market"),
            ("risks_and_limitations", "Risks and limitations"))


@dataclass
class CheckedStatement:
    section: str
    text: str
    kind: str
    item_ids: list[str]


@dataclass
class CheckedReport:
    headline: Optional[CheckedStatement]
    statements: list[CheckedStatement] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)      # (statement text, reason)
    unavailable: list[str] = field(default_factory=list)


class AnalystUnavailable(Exception):
    """A readable reason the analysis could not be produced (shown to the user as-is)."""


# ------------------------------------------------------------------ checks --

def check_statement(s: Statement, payload: dict, allowed) -> Optional[str]:
    """None if the statement passes, otherwise the reason it is rejected."""
    bad = unsupported_numbers(s.text, allowed)
    if bad:
        return f"contains figure(s) not produced by the engine: {', '.join(bad)}"
    by_id = {i["id"]: i for i in payload["items"]}
    unknown = [i for i in s.item_ids if i not in by_id]
    if unknown:
        return f"cites unknown item(s): {', '.join(unknown)}"
    kinds = {by_id[i]["provenance"] for i in s.item_ids}
    if s.kind == "fact" and (not kinds or kinds != {"fact"}):
        return "tagged as fact but does not rely only on reported facts"
    if s.kind == "calculated" and (not kinds or not kinds <= {"calculated", "calculated_from_assumptions"}):
        return "tagged as calculated but cites items that are not engine outputs"
    if s.kind == "assumption" and not kinds & {"assumption", "calculated_from_assumptions"}:
        return "tagged as assumption but cites no assumption"
    return None


def check_report(report: AnalystReport, payload: dict) -> CheckedReport:
    allowed = allowed_numbers(payload)
    out = CheckedReport(headline=None,
                        unavailable=[u for u in report.unavailable if not unsupported_numbers(u, allowed)])
    reason = check_statement(report.headline, payload, allowed)
    if reason:
        out.rejected.append((report.headline.text, reason))
    else:
        out.headline = CheckedStatement("Headline", report.headline.text, report.headline.kind,
                                        report.headline.item_ids)
    for key, title in SECTIONS:
        for s in getattr(report, key):
            reason = check_statement(s, payload, allowed)
            if reason:
                out.rejected.append((s.text, reason))
            else:
                out.statements.append(CheckedStatement(title, s.text, s.kind, s.item_ids))
    return out


# -------------------------------------------------------------------- call --

def ask_analyst(payload: dict, api_key: str, client=None) -> CheckedReport:
    """One structured Claude call, then the checks. Raises AnalystUnavailable with a readable reason."""
    client = client or anthropic.Anthropic(api_key=api_key)
    try:
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                  # on a safety decline, the API retries on a fallback model
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Deal payload:\n" + json.dumps(payload, ensure_ascii=False)}],
            output_format=AnalystReport,
        )
    except anthropic.AuthenticationError:
        raise AnalystUnavailable("The API key was rejected. Check ANTHROPIC_API_KEY in .streamlit/secrets.toml.")
    except anthropic.RateLimitError:
        raise AnalystUnavailable("The Claude API rate limit was reached. Try again in a minute.")
    except anthropic.APIStatusError as exc:
        raise AnalystUnavailable(f"The Claude API returned an error ({exc.status_code}). Try again later.")
    except anthropic.APIConnectionError:
        raise AnalystUnavailable("Could not reach the Claude API. Check the internet connection.")
    if response.stop_reason == "refusal":
        raise AnalystUnavailable("The model declined to analyse this deal.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AnalystUnavailable("The analysis was incomplete. Try again.")
    return check_report(response.parsed_output, payload)
