"""
Shared test fixtures.

The app lists deals from data/sample_deals/ and data/user_deals/. App tests use
isolated_deal_folders so they always see the same two deals (the illustrative
fixture + Microsoft / Activision) and never the developer's own saved deals.
"""

import shutil
from pathlib import Path

import pytest

import ui.ai_panel
import ui.settings

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


@pytest.fixture(autouse=True)
def no_real_settings(monkeypatch):
    """Tests never see the developer's .streamlit/secrets.toml or environment settings.

    Above all this keeps a real ANTHROPIC_API_KEY out of the tests, so no test can make a paid
    API call; it also keeps local choices (e.g. DEALLENS_AI_SESSION_LIMIT) from changing test results.
    Tests that need a setting patch it explicitly.
    """
    monkeypatch.setattr(ui.settings, "setting", lambda name: None)
    monkeypatch.setattr(ui.ai_panel, "setting", lambda name: None)
