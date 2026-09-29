"""
Landing page: a dark full-height hero rendered with st.html.

Navigation: Streamlit callbacks cannot be triggered from inside HTML, so the links
carry a query parameter (?go=new, ?go=example) that app.py reads on load to open
the right section, then clears.

The stats row is filled live by the engine from the example deal (never
hard-coded figures); it is left out if the example deal is missing.

The landing CSS is scoped under .dl-landing. HOME_PAGE_CSS is the one exception:
it is only rendered on Home and makes the page full-screen (no sidebar, header or
padding); every other section keeps the normal layout.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

import streamlit as st

from finance.transaction import analyse_transaction
from utils.formatting import format_value
from utils.io import load_deal

ASSETS = Path(__file__).parent.parent / "assets"
STAT_METRICS = (("ev_ebitda", "EV / EBITDA"), ("premium", "Premium"), ("enterprise_value", "Enterprise value"))

# Home only: full-screen dark page. Hides the sidebar (and its expand button) and the header,
# removes the main container's padding and width limit.
HOME_PAGE_CSS = """<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"], [data-testid="stHeader"] { display: none !important; }
[data-testid="stMainBlockContainer"] { padding: 0 !important; max-width: 100% !important; }
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stAppViewContainer"], [data-testid="stMain"] { background: #08060E !important; }
</style>"""


def example_stats(path: Optional[Path]) -> Optional[list[tuple[str, str]]]:
    """(display value, label) for the example deal's headline metrics, calculated by the engine."""
    if path is None:
        return None
    analysis = analyse_transaction(load_deal(path))
    cur = analysis.inputs.info.currency
    return [(format_value(analysis.value(k), analysis.metrics[k].unit, cur), label) for k, label in STAT_METRICS]


def render_home(stats: Optional[list[tuple[str, str]]], example_title: str = "") -> None:
    st.html(HOME_PAGE_CSS + landing_html(stats, example_title))


def landing_html(stats: Optional[list[tuple[str, str]]], example_title: str = "") -> str:
    esc = html.escape
    example_link = ('<a href="?go=example" target="_self" class="dl-ghost">Try an example &nbsp;→</a>'
                    if stats else "")
    stats_html = ""
    if stats:
        items = "".join(f'<div><div class="dl-stat-value">{esc(v)}</div><div class="dl-stat-label">{esc(k)}</div></div>'
                        for v, k in stats)
        stats_html = (f'<div class="dl-stats-wrap"><div class="dl-stats">{items}</div>'
                      f'<div class="dl-stats-note">{esc(example_title)} · calculated by DealLens</div></div>')
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
.dl-landing {{
  --dl-bg: #08060E; --dl-fg: #FFFFFF; --dl-muted: rgba(255,255,255,0.45);
  --dl-font: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  position: relative; overflow: hidden; height: 100vh; min-height: 560px;
  background: var(--dl-bg); color: var(--dl-fg); font-family: var(--dl-font);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding-inline: 24px; color-scheme: dark;
}}
.dl-landing *, .dl-landing *::before, .dl-landing *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
.dl-landing a {{ text-decoration: none; }}
.dl-orb-wrap {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  pointer-events: none; }}
.dl-orb {{ width: min(560px, 80vw); height: min(560px, 80vw); border-radius: 50%; position: relative;
  flex-shrink: 0;
  background:
    radial-gradient(circle at 35% 38%, rgba(140,80,220,0.95) 0%, transparent 55%),
    radial-gradient(circle at 68% 30%, rgba(80,120,255,0.70) 0%, transparent 48%),
    radial-gradient(circle at 55% 70%, rgba(220,80,60,0.75) 0%, transparent 50%),
    radial-gradient(circle at 20% 65%, rgba(180,60,200,0.60) 0%, transparent 45%),
    radial-gradient(circle at 78% 65%, rgba(100,60,180,0.50) 0%, transparent 40%),
    radial-gradient(circle at 50% 50%, rgba(60,30,100,1) 0%, rgba(20,10,40,1) 100%);
  box-shadow: 0 0 120px 40px rgba(140,80,220,0.30), 0 0 240px 80px rgba(100,60,180,0.18),
    inset 0 0 80px 0 rgba(255,255,255,0.04);
  animation: dl-breathe 6s ease-in-out infinite; }}
.dl-orb::after {{ content: ''; position: absolute; inset: 0; border-radius: 50%;
  border: 1.5px solid rgba(200,160,255,0.25); box-shadow: inset 0 0 40px rgba(200,160,255,0.08); }}
@keyframes dl-breathe {{ 0%, 100% {{ transform: scale(1); filter: brightness(1); }}
  50% {{ transform: scale(1.025); filter: brightness(1.07); }} }}
.dl-content {{ position: relative; z-index: 5; text-align: center; display: flex; flex-direction: column;
  align-items: center; }}
.dl-headline {{ font-size: clamp(52px, 10vw, 96px); font-weight: 300; letter-spacing: -0.04em;
  line-height: 1.0; color: #fff; text-shadow: 0 2px 40px rgba(0,0,0,0.6); margin-bottom: 36px; }}
.dl-headline strong {{ font-weight: 600; }}
.dl-actions {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; justify-content: center; }}
.dl-primary {{ background: rgba(255,255,255,0.95); color: #08060E !important; font-weight: 600; font-size: 14px;
  padding: 13px 28px; border-radius: 50px; transition: opacity .2s; letter-spacing: -0.01em; }}
.dl-primary:hover {{ opacity: 0.88; }}
.dl-ghost {{ color: rgba(255,255,255,0.60) !important; font-size: 13px; padding: 13px 4px; transition: color .2s; }}
.dl-ghost:hover {{ color: #fff !important; }}
.dl-bottom {{ position: absolute; bottom: 32px; left: 40px; right: 40px; display: flex;
  justify-content: space-between; align-items: flex-end; z-index: 10; }}
.dl-stats {{ display: flex; gap: 36px; }}
.dl-stat-value {{ font-size: 22px; font-weight: 500; letter-spacing: -0.02em; color: #fff; line-height: 1;
  margin-bottom: 4px; }}
.dl-stat-label {{ font-size: 10px; font-weight: 500; letter-spacing: .10em; text-transform: uppercase;
  color: var(--dl-muted); }}
.dl-stats-note {{ font-size: 10px; color: var(--dl-muted); margin-top: 10px; letter-spacing: .02em; }}
.dl-tagline {{ font-size: 11px; color: var(--dl-muted); letter-spacing: .04em; text-align: right; line-height: 1.6; }}
@media (max-width: 600px) {{
  .dl-bottom {{ left: 20px; right: 20px; bottom: 20px; }}
  .dl-stats {{ gap: 20px; }} .dl-stat-value {{ font-size: 18px; }} .dl-tagline {{ display: none; }}
  .dl-headline {{ font-size: clamp(44px, 14vw, 72px); }}
}}
@media (prefers-reduced-motion: reduce) {{ .dl-orb {{ animation: none; }} }}
</style>
<div class="dl-landing">
  <div class="dl-orb-wrap"><div class="dl-orb"></div></div>
  <div class="dl-content">
    <h1 class="dl-headline">deal<strong>lens.</strong></h1>
    <div class="dl-actions">
      <a href="?go=new" target="_self" class="dl-primary">Analyse a deal</a>
      {example_link}
    </div>
  </div>
  <div class="dl-bottom">
    {stats_html}
    <div class="dl-tagline">Every figure calculated in Python.<br>Every assumption labelled.</div>
  </div>
</div>
"""
