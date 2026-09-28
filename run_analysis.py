"""
Run the transaction engine on a deal file and print the results.

    python run_analysis.py                                  # illustrative deal
    python run_analysis.py data/sample_deals/microsoft_activision.json     # any deal file
"""

import sys
from dataclasses import asdict

from finance.models import DealInputError
from finance.transaction import analyse_transaction
from utils.formatting import format_value
from utils.io import load_deal

DEFAULT_DEAL = "tests/fixtures/illustrative_deal.json"   # round numbers, checkable by hand


def main(path: str) -> int:
    try:
        deal = load_deal(path)
        analysis = analyse_transaction(deal)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}")
        return 1
    except DealInputError as exc:
        print(f"ERROR: {exc}")
        return 1

    info, cur = deal.info, deal.info.currency
    print(f"\nDEALLENS | {info.acquirer} / {info.target} | {info.sector} | "
          f"{deal.facts.financials_period} | {cur} millions")

    print("\nINPUTS — FACTS")
    for k, v in asdict(deal.facts).items():
        if k == "share_build":
            continue
        print(f"  {k:<36}{'—' if v is None else v}")
    build = deal.facts.share_build
    if build is not None:
        print("  share_build")
        print(f"    {'basic_shares':<34}{build.basic_shares}")
        for i, t in enumerate(build.option_tranches):
            print(f"    {f'option_tranches[{i}]':<34}{t.number} @ strike {t.strike}")
        print(f"    {'rsus':<34}{build.rsus}")
        if build.as_of:
            print(f"    {'as_of':<34}{build.as_of}")
    print("\nINPUTS — ASSUMPTIONS")
    for k, v in asdict(deal.assumptions).items():
        print(f"  {k:<36}{'—' if v is None else v}")

    section = None
    for m in analysis.metrics.values():
        if m.section != section:
            section = m.section
            print(f"\n{section.upper()}")
        tag = "[A]" if m.depends_on_assumptions else "   "
        print(f"  {tag} {m.label:<46}{format_value(m.value, m.unit, cur):>11}   {m.formula}")
        if m.note:
            print(f"      ↳ {m.note}")

    print("\n[A] = depends on user assumptions; all other metrics use facts only.")
    print("\nWARNINGS" if analysis.warnings else "\nNo warnings.")
    for w in analysis.warnings:
        print(f"  ! {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DEAL))
