"""
Shared test fixtures.

The app lists deals from data/sample_deals/ and data/user_deals/. App tests use
isolated_deal_folders so they always see the same two deals (the illustrative
fixture + Microsoft / Activision) and never the developer's own saved deals.
"""

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ILLUSTRATIVE_FILE = ROOT / "tests" / "fixtures" / "illustrative_deal.json"
ACTIVISION_FILE = ROOT / "data" / "sample_deals" / "microsoft_activision.json"


@pytest.fixture
def isolated_deal_folders(tmp_path, monkeypatch):
    samples, saved = tmp_path / "sample_deals", tmp_path / "user_deals"
    samples.mkdir()
    for f in (ILLUSTRATIVE_FILE, ACTIVISION_FILE):
        shutil.copy(f, samples / f.name)
    monkeypatch.setattr("utils.io.SAMPLE_DEALS_DIR", samples)
    monkeypatch.setattr("utils.io.USER_DEALS_DIR", saved)
    return saved
