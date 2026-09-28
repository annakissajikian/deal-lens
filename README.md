# DealLens — AI-Powered M&A Analyst

A preliminary M&A screening tool. Every financial metric is calculated
deterministically in Python. AI (added in a later step) will only interpret
these results; it is never used as a calculator.

> Preliminary analytical tool for educational purposes. Not investment advice.

## Status

**Step 1 — Transaction engine.** Complete.
**Step 2 — Fully diluted shares (treasury stock method).** Engine complete;
real-deal test case (Microsoft / Activision Blizzard) in progress.
Command line only; the interface comes later.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run_analysis.py             # analyse the illustrative deal
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
├── data/sample_deals/illustrative_deal.json
└── tests/
    ├── test_transaction.py      # hand-calculated finance results
    ├── test_dilution.py         # hand-calculated treasury stock method
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
