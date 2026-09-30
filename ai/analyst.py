"""
AI analyst (Step 6): Claude interprets the engine's outputs; it never calculates.

Flow:
  1. build_payload() -> the only data the model sees (ai/payload.py)
  2. ask_analyst()   -> one Claude API call with a structured output (AnalystReport)
  3. check_report()  -> every statement is verified before it is shown (chat answers too,
                        via ask_question() / check_answer()):
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

Your view:
- Give a clear view, as a senior deal team member would. Say whether the deal looks attractive, fair,
  full or stretched for the buyer (and whether the offer looks compelling for target shareholders),
  and why. Make the headline your overall view when the evidence supports one.
- Weigh the evidence: where the offer sits against the DCF, trading comps, precedent transactions and
  market references; the size of the premium; how demanding the multiples are; how much of the value
  depends on assumptions.
- Flag the main risks explicitly (valuation, assumption sensitivity, missing synergy support, data gaps)
  and say what would change your view.
- Opinions and recommendations are "interpretation" statements. They follow the same number rule: cite
  only figures from the payload, and cite the item ids your view rests on. If the payload is too thin
  to support a view, say so rather than guessing.
- Be concise and specific; write for an investment banking analyst. The app shows its own disclaimer.
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

def _parse(client, **request):
    """One structured Claude call; API failures become AnalystUnavailable with a readable reason."""
    try:
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                  # on a safety decline, the API retries on a fallback model
            **request,
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
        raise AnalystUnavailable("The model declined to answer.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AnalystUnavailable("The answer was incomplete. Try again.")
    return response.parsed_output


def ask_analyst(payload: dict, api_key: str, client=None) -> CheckedReport:
    """One structured Claude call, then the checks. Raises AnalystUnavailable with a readable reason."""
    report = _parse(client or anthropic.Anthropic(api_key=api_key),
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": "Deal payload:\n" + json.dumps(payload, ensure_ascii=False)}],
                    output_format=AnalystReport)
    return check_report(report, payload)


# -------------------------------------------------------------------- chat --

CHAT_SYSTEM_PROMPT = """You answer questions from a banking team about one M&A transaction.
The deal payload below was produced by a deterministic Python valuation engine. Answer only from it.

Rules:
- Every number you write must be copied exactly as it appears in an item's "display" value (same
  rounding and units). Never calculate, round, convert (no "bn"), estimate or project a figure, and
  never repeat a number from the question that is not in the payload.
- If the question needs a figure, scenario or data the engine did not produce (for example a
  different WACC, offer price or synergy case), do not compute it: say it is unavailable because the
  engine has not calculated it, and add it to "unavailable". Suggest where it could come from if useful
  (for example: change the input in the New deal form and re-run the engine).
- Answer in one to four short statements. Tag each: fact (reported input), assumption, calculated
  (engine output) or interpretation (your judgement), and cite the payload item ids it relies on.
- When asked for a view (is the deal attractive, is the price fair, what are the risks, would you
  recommend it), give one clearly and explain why, as an "interpretation" statement grounded in the
  payload figures. Say what it depends on (for example DCF assumptions) and what would change it.
  If the payload cannot support a view, say so rather than guessing.
- Previous answers in the conversation were checked; stay consistent with them.
"""


class ChatAnswer(BaseModel):
    statements: list[Statement] = Field(description="One to four statements answering the question.")
    unavailable: list[str] = Field(description="Data needed for the question that is not in the payload.")


@dataclass
class ChatTurn:
    question: str
    statements: list[CheckedStatement] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    error: str = ""                                 # set when the call failed (shown instead of an answer)

    def answer_text(self) -> str:
        """What the model said, as it goes back into the history: only statements that passed the checks."""
        if self.error:
            return f"(No answer: {self.error})"
        lines = [f"[{s.kind}] {s.text}" for s in self.statements]
        lines += [f"[unavailable] {u}" for u in self.unavailable]
        return "\n".join(lines) or "(No statement passed the number checker.)"


def check_answer(question: str, answer: ChatAnswer, payload: dict) -> ChatTurn:
    allowed = allowed_numbers(payload)
    turn = ChatTurn(question, unavailable=[u for u in answer.unavailable if not unsupported_numbers(u, allowed)])
    for s in answer.statements:
        reason = check_statement(s, payload, allowed)
        if reason:
            turn.rejected.append((s.text, reason))
        else:
            turn.statements.append(CheckedStatement("Answer", s.text, s.kind, s.item_ids))
    return turn


def chat_messages(history: list[ChatTurn], question: str) -> list[dict]:
    """Earlier questions and their checked answers, then the new question (append-only history)."""
    messages: list[dict] = []
    for turn in history:
        messages += [{"role": "user", "content": turn.question},
                     {"role": "assistant", "content": turn.answer_text()}]
    return messages + [{"role": "user", "content": question}]


def ask_question(payload: dict, history: list[ChatTurn], question: str, api_key: str, client=None) -> ChatTurn:
    """Answer one question about the deal; the answer is checked like the analysis. Never raises."""
    try:
        answer = _parse(client or anthropic.Anthropic(api_key=api_key),
                        system=[{"type": "text", "text": CHAT_SYSTEM_PROMPT},
                                {"type": "text", "text": "Deal payload:\n" + json.dumps(payload, ensure_ascii=False),
                                 "cache_control": {"type": "ephemeral"}}],     # same payload every question
                        messages=chat_messages(history, question),
                        output_format=ChatAnswer)
    except AnalystUnavailable as exc:
        return ChatTurn(question, error=str(exc))
    return check_answer(question, answer, payload)
