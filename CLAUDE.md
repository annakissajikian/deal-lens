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
   *Working mode from 29 Sep 2026 (Anna's request, to finish the project):*
   for each step build → run all tests → commit when green → give a SHORT
   summary (what was built, the key finance concept in 3 lines, how to see it
   in the app) → move straight to the next step. Stop only for decisions that
   are genuinely Anna's (e.g. DCF assumptions, API key setup, account
   creation for deployment). All other rules still apply.
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
- **Step 2 — COMPLETE.** 137 tests pass (95 Step 1 + 31 Step 2a + 11 Step 2b).
- **Step 2a — Fully diluted shares (treasury stock method): COMPLETE.**
  31 tests in `tests/test_dilution.py`.
  `finance/dilution.py` applies TSM tranche by tranche at the offer price.
  Deals give either `diluted_shares_outstanding` or a `share_build`
  (basic shares, option tranches, RSUs/PSUs); if both, the build is used and
  a >1% gap is a WARNING. Decisions agreed with Anna: the offer-price share
  count is also used for unaffected equity value (stated limitation); cash =
  cash and equivalents only; PSUs counted at target.
  Step 1 outputs above are unchanged.
- **Step 2b — Microsoft / Activision Blizzard test case: COMPLETE and locked.**
  `data/sample_deals/microsoft_activision.json` (every fact has `_sources`:
  document, section, PDF/printed page, as-of date, snippet) + 11 tests in
  `tests/test_activision.py`. Core outputs: fully diluted shares 795.76m;
  equity value 75,597; EV 68,824 (vs $68.7bn headline, +0.18%); premium 45.3%;
  EV/Revenue 7.82x; EV/EBITDA 20.39x; unaffected EV/EBITDA 13.41x;
  EBITDA margin 38.3%. These must not change unless a source figure is corrected.
  Decisions agreed with Anna: share data from Merger Agreement s.3.7
  (13 Jan 2022) with the 10-K $57.77 weighted-average strike as one tranche
  (no range table in the 10-K); gross debt 3,650 (not 3,608 carrying value);
  EBITDA = operating income 3,259 + D&A 116 = 3,375, capitalised software
  amortisation NOT added back; `stated_equity_value` empty because the
  $68.7bn headline is net of cash (compared with EV in `_cross_checks`);
  synergies 0 (none disclosed); 100% cash. The DEFM14A does not state the
  unaffected close in dollars: $65.39 comes from Investing.com (screenshot in
  `data/sources/`) and matches the proxy's 45.3% premium.
- **Step 3 — Streamlit MVP: COMPLETE.** 155 tests pass (18 new: 13 in
  `tests/test_app.py` using Streamlit's headless `AppTest`, 5 in
  `tests/test_validation.py`). `streamlit==1.64.0` is the only new dependency.
  `app.py` + `ui/overview.py` + `ui/financials.py` display results only;
  nothing is calculated in the UI. Run: `streamlit run app.py`.
  - Sidebar dropdown lists every file in `data/sample_deals/`
    (`utils/io.list_sample_deals`); disclaimer in sidebar and footer.
  - Deal Overview: EV, equity value, premium, EV/EBITDA tiles; deal terms;
    warnings. A "not provided" warning for a field that is empty AND has a
    `_sources` note is shown as a blue info note with that reason
    (`ui/overview.intentionally_empty`). The engine and `run_analysis.py`
    still emit the warning.
  - Financials: tables tagged Fact / Fact · derived (a `_sources` note
    starting "CALCULATED") / Assumption / Calculated / Calculated · uses
    assumptions; metric notes as captions; Sources section (documents,
    figures table + "Figure detail" selector, cross-checks, evidence image).
  - Source text shown via markdown must go through `utils/formatting.md()`,
    which escapes "$": otherwise Streamlit renders text between two "$" as a
    maths formula and misquotes filings.
  - Known cosmetic limitation: long deal names are cut short in the sidebar
    dropdown (fixing it needs custom CSS).
- **Step 3b — "New deal" input form: COMPLETE.** 179 tests pass (24 new in
  `tests/test_deal_form.py`). Sidebar mode "Enter a new deal" →
  `ui/deal_form.py`: tabs Inputs / Deal Overview / Financials; "Start from"
  prefill; five groups (deal info, deal terms, share count incl. TSM tranche
  table, target financials, assumptions); Run shows an error summary plus
  each error under its group; download JSON; save to `data/user_deals/`
  (listed in the dropdown as "Saved: ..."; tracked by git; never overwrites
  without the "Overwrite" tick box).
  Decisions agreed with Anna: percentages typed as 25 for 25% (converted to
  0.25 only in `build_deal_dict`); saved deals in `data/user_deals/`, not
  gitignored; on Streamlit Cloud saving is not persistent, so decide in
  Step 11 whether to hide Save when deployed (Download always works).
  Rules for future UI work:
  - Every deal, from a file or the form, goes through
    `utils/io.deal_from_dict()`; never build `DealInputs` another way.
  - Every `st.number_input` for an optional or required figure needs
    `value=None`, otherwise clearing it silently becomes 0.
  - Streamlit deletes the state of widgets that are not drawn: the form
    keeps `st.session_state.f_saved` as the persistent copy.
  - Tabs that share a label with another view need their own `key`/`default`.
  - No `st.form`: results hide when inputs change after a run.
- **Step 4 — DCF + WACC / terminal-growth sensitivity: COMPLETE.** 216 tests.
  `finance/dcf.py` (end-of-year discounting, Gordon growth TV; all DCF
  metrics depend_on_assumptions); optional `dcf` JSON section → `DCFInputs`;
  WACC ≤ g is an ERROR, TV > 75% of EV / g > 4% / WACC outside 5–20% are
  WARNINGs. DCF tab (saved deals and form) with Altair heatmap: diverging
  blue (above offer) / grey `#f0efec` (at offer) / red (below), Lab
  interpolation. Layered Altair charts that mix a numeric colour scale with
  literal text colours need `resolve_scale(color="independent")`, otherwise
  they render at zero height. Activision (agreed with Anna): proxy management
  UFCF 2022E–2026E, WACC 7.25% / g 2.50% (Allen & Co midpoints) → $99.03 per
  share, EV 72,030; grid $83.52–$122.79 vs Allen $84.73–$123.87. Locked.
- **Step 5 — Comps + precedents + football field: COMPLETE.** 244 tests.
  `finance/comps.py`: optional `valuation` JSON section (`multiples` with
  peers and/or a selected range, default = peers' interquartile range;
  `references` per-share ranges). Valuation tab: football field (categorical
  palette slots 1–4 in fixed order: DCF, Trading comps, Precedent transactions,
  Market reference; offer = solid line, unaffected = dashed) + comps table.
  Form: tables for methods, peers and reference ranges. Activision uses Allen
  & Co's selected ranges × management Adj. EBITDA (within 1% of Allen's
  per-share ranges) + 52-week range and analyst targets. Locked.
- **Step 6 — AI analyst: COMPLETE (code + tests; live call awaits Anna's API
  key).** 263 tests. `ai/payload.py` (engine outputs only, provenance per item,
  "unavailable" list), `ai/number_checker.py` (every number in AI text must
  appear in the payload; signs/commas/trailing zeros ignored),
  `ai/analyst.py` (`client.beta.messages.parse`, `claude-opus-5-5`,
  `output_format=AnalystReport`, `fallbacks="default"` with beta
  `server-side-fallback-2026-07-01`; statements removed on unsupported
  numbers, unknown item ids or kind/provenance mismatch). `anthropic==1.9.0`
  added. Key from `st.secrets` / env only. Tests never call the API.
- **Step 7 — Deal memo: COMPLETE.** 271 tests. `reports/memo.py` builds HTML
  (self-contained CSS, football field in HTML/CSS, prints to PDF) + Markdown
  from templates filled with engine figures; optional AI section only from a
  `CheckedReport`. Memo tab with "Generate Deal Memo" + two downloads. A test
  runs the number checker over the whole memo.
- **Step 8 — Visual polish + landing page: COMPLETE.** 274 tests. Sidebar
  sections Home / Example & saved deals / New deal (radio key `mode`; deal
  selectbox key `deal`); landing page `ui/home.py` with "Analyse a deal" and
  "Try the example" (callbacks set `mode`/`deal`); `assets/logo_mark.svg` +
  `logo_wordmark.svg` via `st.logo`; brand navy `#1F3A5F`, accent `#2A78D6`.
  Sample deals are labelled "Example: …", user deals "Saved: …". App tests
  must switch `mode` first (the landing page is the default view).
- **Step 9 — Deploy to Streamlit Community Cloud: IN PROGRESS.** Code ready,
  277 tests. Decisions (Anna, 29 Sep 2026): public GitHub repo; AI analyst on
  with Anna's key + cap of 3 analyses per visitor session
  (`DEALLENS_AI_SESSION_LIMIT`); Save hidden online (`DEALLENS_ALLOW_SAVE =
  "false"`). Settings read by `ui/settings.py` from `st.secrets` / env;
  template `.streamlit/secrets.toml.example`. README rewritten for the CV
  with screenshots in `docs/screenshots/`; live URL still to be added.
  Waiting for Anna: Anthropic API key (local test first), GitHub repo +
  `git push`, Streamlit Cloud app + secrets.

## Roadmap (agreed with Anna on 29 Sep 2026)
Done: 1 transaction engine · 2 fully diluted shares + Activision · 3 Streamlit
MVP · 3b New deal form.
4. DCF + WACC / terminal-growth sensitivity (colour-coded heatmap)
5. Comparable companies + precedent transactions (manual table entry, kept
   simple) + football field chart
6. AI analyst: the LLM interprets engine outputs only, never calculates;
   distinguishes facts / assumptions / calculated / AI interpretation; says
   "unavailable" rather than inventing data
7. Deal memo: "Generate Deal Memo" button, downloadable
8. Visual polish: landing page (DealLens name, one-line pitch, "Analyse a
   deal" button), small consistent brand (logo, palette, spacing)
9. Deploy to Streamlit Community Cloud with a public URL

Deals in the app: Microsoft / Activision is a one-click "Example deal", not
the default view. The illustrative Northwind deal is kept for tests only
(`tests/fixtures/illustrative_deal.json`).

### Future work (postponed on 29 Sep 2026)
- Sources & uses, accretion/dilution, pro forma leverage (needs acquirer data)
- Annual-report PDF extraction with page citations (user confirms values)
- CSV upload for comps / precedents

## Architecture
```
deal-lens/
├── run_analysis.py
├── finance/        # deterministic engine: models, validation, transaction (+ dcf, comps, ... later)
├── utils/          # io (JSON loading), formatting
├── data/sample_deals/
├── tests/
├── ai/             # AI analyst: payload, number checker, Claude call
├── extraction/     # future work: PDF parsing with citations
├── reports/        # deal memo
└── ui/ + app.py    # Streamlit app (display only)
```

## Disclaimer to keep in the UI and README
Preliminary analytical tool for educational purposes. Not investment advice.
