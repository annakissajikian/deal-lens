"""
Deployment settings, read from Streamlit secrets (.streamlit/secrets.toml locally,
the app's Secrets on Streamlit Cloud) or environment variables. Never from code.

    ANTHROPIC_API_KEY          enables the AI analyst
    DEALLENS_AI_SESSION_LIMIT  AI analyses allowed per visitor session (default 3)
"""

from __future__ import annotations

import os
from typing import Optional

import streamlit as st

DEFAULT_AI_SESSION_LIMIT = 3


def setting(name: str) -> Optional[str]:
    try:
        value = st.secrets.get(name)
    except Exception:                 # no secrets file at all
        value = None
    value = value if value not in (None, "") else os.environ.get(name)
    return None if value in (None, "") else str(value)


def ai_session_limit() -> int:
    try:
        return max(0, int(setting("DEALLENS_AI_SESSION_LIMIT") or DEFAULT_AI_SESSION_LIMIT))
    except ValueError:
        return DEFAULT_AI_SESSION_LIMIT
