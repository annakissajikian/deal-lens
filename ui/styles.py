"""
Dark theme details that .streamlit/config.toml cannot express (visual only).

The theme (config.toml) sets the colours of everything Streamlit draws: page,
sidebar, inputs, tables, alerts, charts. This CSS adds the landing page's style:
white pill primary buttons, ghost secondary buttons, card-style metric tiles,
muted inactive tabs with a gold indicator, and muted captions.
"""

from __future__ import annotations

import streamlit as st

BG, CARD, FG, MUTED, INACTIVE, BORDER, GOLD = (
    "#08060E", "#1A1625", "#FFFFFF", "rgba(255,255,255,0.55)", "rgba(255,255,255,0.35)",
    "rgba(255,255,255,0.08)", "#C9A84C")

APP_CSS = f"""<style>
/* Primary buttons: white pill with dark text (landing page .btn-primary) */
[data-testid="stBaseButton-primary"] {{
  background: rgba(255,255,255,0.95) !important; color: {BG} !important; border: none !important;
  border-radius: 50px !important; font-weight: 600 !important; padding-inline: 22px !important;
}}
[data-testid="stBaseButton-primary"]:hover {{ opacity: 0.88; }}
[data-testid="stBaseButton-primary"] p {{ color: {BG} !important; }}
/* Secondary and download buttons: ghost pill */
[data-testid="stBaseButton-secondary"] {{
  background: transparent !important; color: rgba(255,255,255,0.75) !important;
  border: 1px solid rgba(255,255,255,0.20) !important; border-radius: 50px !important;
}}
[data-testid="stBaseButton-secondary"]:hover {{ color: {FG} !important; border-color: rgba(255,255,255,0.45) !important; }}
/* Metric tiles: cards */
[data-testid="stMetric"] {{ background: {CARD}; border-color: {BORDER} !important; border-radius: 14px; }}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {{ color: {MUTED} !important; }}
/* Tabs: muted inactive labels, white active label, gold indicator (theme primary colour) */
[data-testid="stTab"] p {{ color: {INACTIVE}; }}
[data-testid="stTab"][aria-selected="true"] p {{ color: {FG}; }}
[data-baseweb="tab-highlight"] {{ background-color: {GOLD} !important; }}
[data-baseweb="tab-border"] {{ background-color: {BORDER} !important; }}
/* Muted secondary text */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {MUTED} !important; }}
/* Bordered containers (tiles, expanders, memo preview): subtle borders */
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stExpander"] details {{ border-color: {BORDER} !important; }}
</style>"""


def apply_styles() -> None:
    st.html(APP_CSS)
