# DealLens — AI-Powered M&A Analyst

A preliminary M&A screening tool. Every financial metric is calculated
deterministically in Python. AI (added in a later step) will only interpret
these results; it is never used as a calculator.

> Preliminary analytical tool for educational purposes. Not investment advice.

## Status

**Step 1 — Transaction engine.** Complete.
**Step 2 — Fully diluted shares (treasury stock method).** Complete, with a
real-deal test case: Microsoft / Activision Blizzard (see below).
Command line only; the interface comes later.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run_analysis.py             # analyse the illustrative deal
python run_analysis.py data/sample_deals/microsoft_activision.json   # real deal
python -m pytest -v                # run the tests
```

## Project structure

```
deal-lens/
├── run_analysis.py              # command-line demo
├── finance/                     # deterministic engine, no AI
│   ├── models.py                # DealInfo, DealFacts, DealAssumptions, Metric
│   ├── validation.py            # errors (stop) and warnings (review)
│   ├── dilution.py              # fully diluted shares (treasury stock method)
│   └── transaction.py           # the formulas
├── utils/
│   ├── io.py                    # JSON file -> DealInputs
│   └── formatting.py            # 13.60x, 20.0%, $6,000m, n.m.
├── data/
│   ├── sample_deals/illustrative_deal.json     # round numbers, checkable by hand
│   ├── sample_deals/microsoft_activision.json  # real deal, every figure sourced
│   └── sources/                                # saved evidence (e.g. share price screenshot)
└── tests/
    ├── test_transaction.py      # hand-calculated finance results
    ├── test_dilution.py         # hand-calculated treasury stock method
    ├── test_activision.py       # real-deal regression test
    └── test_validation.py       # rejected and flagged inputs
```

## Conventions

- Money and shares in **millions**; prices **per share**.
- Percentages as decimals: `0.30` = 30%.
- Multiples with a missing, zero or negative denominator show **n.m.**
- Metrics marked **[A]** depend on user assumptions; all others use facts only.

## Formulas

| Metric | Formula |
|---|---|
| Options exercised (TSM) | Σ options with strike < offer price, tranche by tranche |
| Shares repurchased (TSM) | Σ (options × strike) ÷ offer price |
| Fully diluted shares | Basic shares + options exercised − shares repurchased + RSUs/PSUs |
| Transaction equity value | Offer price × Fully diluted shares |
| Transaction enterprise value | Equity value + Debt − Cash |
| Acquisition premium | Offer price ÷ Unaffected (pre-announcement) price − 1 |
| EV / Revenue, EV / EBITDA, EV / EBIT | Transaction EV ÷ metric |
| Equity value / Net income | Transaction equity value ÷ Net income |
| Unaffected EV / EBITDA | (Unaffected price × Diluted shares + Debt − Cash) ÷ EBITDA |
| Revenue synergy EBITDA contribution | Revenue synergies × Incremental margin |
| Pro forma EBITDA | EBITDA + Cost synergies + Revenue synergy EBITDA contribution |
| Synergy-adjusted EV / EBITDA | Transaction EV ÷ Pro forma EBITDA |
| Financing split | Equity value × share of cash / debt / stock |

## Share count

Either enter `diluted_shares_outstanding` directly, or give a `share_build`
in `facts` and DealLens calculates it with the treasury stock method:

```json
"share_build": {
  "basic_shares": 100,
  "option_tranches": [{"number": 6, "strike": 30}, {"number": 4, "strike": 45}],
  "rsus": 2,
  "as_of": "basic 2026-01-10; awards 2025-12-31"
}
```

If both are given, the share build is used and a difference above 1% is flagged.

## Real deal: Microsoft / Activision Blizzard (announced 18 Jan 2022)

Inputs come from Activision's FY2021 10-K, the DEFM14A merger proxy (including
the Merger Agreement) and Microsoft's press release. Each figure's document,
section, page and snippet is recorded under `_sources` in the deal file.

| Output | Value |
|---|---|
| Fully diluted shares (TSM, 13 Jan 2022) | 795.76m |
| Equity value / Enterprise value | $75,597m / $68,824m |
| Premium to 14 Jan 2022 close ($65.39) | 45.3% (proxy: "approximately 45.3%") |
| EV / Revenue, EV / EBITDA (FY2021) | 7.82x, 20.39x |

Cross-check: Microsoft's $68.7bn headline is "inclusive of Activision
Blizzard's net cash", so it is compared with our **enterprise value**
(+0.18%), not equity value.

Judgements specific to this deal: EBITDA = operating income + D&A (capitalised
software amortisation not added back); gross debt of 3,650 rather than the
3,608 carrying value; PSUs at target; all options as one tranche at the
$57.77 weighted-average strike (no range table in the 10-K); synergies set to
zero because none were disclosed. The unaffected close is not stated in the
proxy; it comes from Investing.com (screenshot in `data/sources/`) and matches
the proxy's 45.3% premium.

## Limitations

- Enterprise value excludes preferred stock, minority interests, leases and
  pension liabilities.
- The treasury stock method is applied at the offer price, and that share
  count is also used for the unaffected equity value. At the lower unaffected
  price fewer options would be in the money, so unaffected equity value is
  slightly overstated.
- Each option tranche uses its weighted-average strike. Options inside a range
  can straddle the offer price; a finer table gives a more precise result.
- RSUs and PSUs count one share each; PSUs are counted at target.
- Convertible securities and warrants are not yet modelled.
- A stated headline equity value is only a cross-check; the calculated figure
  is always used.
- If no incremental margin is given, revenue synergies use the target's
  EBITDA margin. This is flagged as an assumption and triggers a warning.
- Synergies are run-rate figures: no phasing, integration costs or valuation.
- The financing split shows how the consideration is funded. It is not pro
  forma leverage or accretion/dilution, which need acquirer financials.
