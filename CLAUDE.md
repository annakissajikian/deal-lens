# DealLens: working instructions for Claude

## Project
DealLens is an AI-powered preliminary M&A analysis tool and a portfolio project for
Anna, a final-year Business Management student aiming for investment banking /
M&A. It must look professional, and Anna must be able to explain every line in
an interview.

Anna has basic/intermediate Python. Act as her senior software engineer, M&A
analyst, finance tutor and project manager.

## Non-negotiable rules
1. **One step at a time.** Build only the current step, then STOP and wait for
   Anna to confirm it works before starting the next one.
2. **Python calculates; AI interprets.** Core financial metrics are always
   computed deterministically in `finance/`. Never use an LLM as a calculator.
   `finance/` must never import from `ai/`.
3. **Never invent financial data.** If a figure is unavailable, say so explicitly.
   Real-deal figures must come from filings, with source and page recorded.
4. **Facts vs assumptions vs calculated vs AI interpretation** must stay
   distinguishable everywhere (see `DealFacts`, `DealAssumptions`,
   `Metric.depends_on_assumptions`).
5. **Do not change working, tested formulas** unless Anna asks, or unless you
   explain a clear finance reason first and she agrees.
6. **Debug, don't rewrite.** When something fails, fix the existing code.
7. **Every finance formula gets tests** with hand-calculated expected values
   written in comments. Test financial correctness, not just that code runs.
8. **Validation:** ERROR = the analysis cannot proceed (raise `DealInputError`
   listing all problems). WARNING = the analysis runs but needs review. No raw
   Python errors should reach the user.
9. No hard-coded outputs. Everything must be reusable across different deals.
10. Clearly label assumptions and limitations (in code notes and the README).
11. Keep the architecture simple. Don't add files, dependencies or
    abstractions without explaining why first.
12. Never commit API keys (use `.env` / `.streamlit/secrets.toml`, both
    gitignored).

## How to present each step
Use this format:

**STEP X — [Name]**
- **Objective:** what we are building
- **Finance concept:** the M&A/valuation idea, explained simply
- **Files:** exactly which files are created or modified
- **Code:** make the changes, then show and explain the diff
- **Explanation:** the important parts of the code, in plain language
- **Test:** exact commands to run
- **Expected result:** what Anna should see
- **Next step:** what comes after she confirms

Before finishing a step, always run `python -m pytest -v` and
`python run_analysis.py` yourself and report the exact results. Then commit
with a clear message (e.g. `Step 2: fully diluted shares`) once Anna confirms.

## Conventions
- Money and shares in **millions**; prices per share; percentages as decimals
  (0.25 = 25%).
- Multiples with a missing, zero or negative denominator return `None` and are
  displayed as "n.m.".
- Metrics are `Metric` objects carrying value, formula, section,
  `depends_on_assumptions` and a note.

## Commands
```bash
python run_analysis.py                     # analyse the illustrative deal
python run_analysis.py path/to/deal.json   # analyse any deal file
python -m pytest -v                        # run all tests
```

## Status
- **Step 1 — Transaction engine: COMPLETE and locked.** 95 tests pass.
  Core outputs for the illustrative deal: equity value 6,000; EV 6,800;
  premium 20%; EV/Revenue 2.72x; EV/EBITDA 13.60x; EBITDA margin 20%;
  pro forma EBITDA 580; synergy-adjusted EV/EBITDA 11.72x.
  These must not change.

## Roadmap (confirm order with Anna before each step)
2. Fully diluted shares (treasury stock method) + a real test case
   (recommended: Microsoft / Activision Blizzard, figures sourced from the
   Activision 10-K and merger proxy with page references)
3. Streamlit MVP: Deal Overview + Financials tabs
4. DCF + WACC / terminal growth sensitivity
5. Comparable companies (manual entry + CSV upload)
6. Precedent transactions + football field chart
7. Sources & uses, accretion/dilution, pro forma leverage (needs acquirer data)
8. AI analyst: structured payload with provenance tags + a number checker
   that rejects any figure the engine didn't produce
9. Annual-report PDF extraction with page citations (user confirms extracted values)
10. Deal memo generation + export
11. Deploy to Streamlit Community Cloud; polish the README for the CV

## Architecture
```
deal-lens/
├── run_analysis.py
├── finance/        # deterministic engine: models, validation, transaction (+ dcf, comps, ... later)
├── utils/          # io (JSON loading), formatting
├── data/sample_deals/
├── tests/
├── ai/             # later: analyst, prompts, number checker
├── extraction/     # later: PDF parsing with citations
├── reports/        # later: deal memo
└── ui/ + app.py    # later: Streamlit
```

## Disclaimer to keep in the UI and README
Preliminary analytical tool for educational purposes. Not investment advice.
