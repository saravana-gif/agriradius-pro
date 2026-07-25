import base64
from functools import lru_cache

import streamlit as st

from config import APP_NAME, LOGO_PATH
from ui.sidebar import sidebar
from ui.layer_manager import layer_manager
from ui.mapview import mapview
from ui.results import results
from ui.project_panel import project_panel


# ----------------------------------------------------------------------
# "Signal" theme - light, readable content with a dark satellite hero.
# Pure CSS + Google Fonts (one request); no JS, so navigation and
# performance are untouched. Responsive down to phone widths.
# ----------------------------------------------------------------------
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');

:root{
  --ink:#0F172A; --ink-soft:#475569; --muted:#64748B;
  --bg:#F5F8FB; --surface:#FFFFFF; --line:#E6EDF3;
  --green:#16A34A; --green-d:#0E7A38; --cyan:#06B6D4; --cyan-d:#0891B2;
  --navy:#0B1F3A;
  --shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.06);
}

/* base type */
html, body, [class*="css"]{ font-family:'Inter',system-ui,sans-serif; }
.block-container{ padding-top:1.4rem; padding-bottom:2.5rem; max-width:1400px; }
header[data-testid="stHeader"]{ background:transparent; }
h1,h2,h3,h4{ font-family:'Space Grotesk','Inter',sans-serif;
  color:var(--ink); font-weight:600; letter-spacing:-.01em; }

/* ---------- Satellite hero band ---------- */
.ar-hero{
  position:relative; overflow:hidden; border-radius:18px;
  padding:22px 26px; margin:2px 0 8px;
  background:
    radial-gradient(120% 140% at 88% -10%, rgba(6,182,212,.34) 0%, rgba(6,182,212,0) 45%),
    linear-gradient(120deg,#0B1F3A 0%, #0C2E33 52%, #0E3D20 100%);
  box-shadow:0 12px 30px rgba(11,31,58,.28);
}
.ar-hero::before{  /* satellite grid */
  content:""; position:absolute; inset:0; opacity:.5;
  background-image:
    linear-gradient(rgba(148,197,255,.10) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148,197,255,.10) 1px, transparent 1px);
  background-size:34px 34px; -webkit-mask-image:linear-gradient(90deg,#000 55%,transparent 100%);
  mask-image:linear-gradient(90deg,#000 55%,transparent 100%);
}
.ar-hero::after{  /* scan glow */
  content:""; position:absolute; right:-60px; top:-70px; width:230px; height:230px;
  border-radius:50%; background:radial-gradient(closest-side, rgba(34,197,94,.30), transparent);
  filter:blur(6px);
}
.ar-hero-row{ position:relative; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.ar-logo{ height:52px; width:auto; border-radius:8px; flex:0 0 auto;
  filter:drop-shadow(0 4px 10px rgba(0,0,0,.35)); background:rgba(255,255,255,.06); padding:6px 10px; }
.ar-mark{ font-size:34px; line-height:1; filter:drop-shadow(0 0 10px rgba(6,182,212,.6)); }
.ar-title{ font-family:'Space Grotesk',sans-serif; color:#fff;
  font-size:1.72rem; font-weight:700; line-height:1.05; letter-spacing:-.02em; }
.ar-sub{ margin-top:3px; color:#9FE7C9; font-size:.74rem; font-weight:600;
  letter-spacing:.16em; text-transform:uppercase; }
.ar-chip{ margin-left:auto; display:inline-flex; align-items:center; gap:7px;
  color:#CFFAFE; font-family:'JetBrains Mono',monospace; font-size:.72rem; font-weight:600;
  background:rgba(6,182,212,.14); border:1px solid rgba(6,182,212,.5);
  border-radius:999px; padding:5px 12px; }
.ar-dot{ width:8px; height:8px; border-radius:50%; background:#22D3EE;
  box-shadow:0 0 0 0 rgba(34,211,238,.7); animation:arpulse 2s infinite; }
@keyframes arpulse{ 0%{box-shadow:0 0 0 0 rgba(34,211,238,.6)} 70%{box-shadow:0 0 0 8px rgba(34,211,238,0)} 100%{box-shadow:0 0 0 0 rgba(34,211,238,0)} }

/* thin note strip under hero */
.ar-note{ font-size:.8rem; color:var(--ink-soft);
  background:var(--surface); border:1px solid var(--line);
  border-left:3px solid var(--cyan); border-radius:10px;
  padding:9px 13px; margin:8px 0 4px; box-shadow:var(--shadow); }
.ar-note b{ color:var(--ink); }

/* ---------- Metric cards ---------- */
div[data-testid="stMetric"]{
  background:var(--surface); border:1px solid var(--line);
  border-radius:14px; padding:14px 16px 12px;
  box-shadow:var(--shadow); position:relative; overflow:hidden;
}
div[data-testid="stMetric"]::before{
  content:""; position:absolute; left:0; top:0; height:3px; width:100%;
  background:linear-gradient(90deg,var(--green),var(--cyan));
}
div[data-testid="stMetricLabel"] p{ color:var(--muted); font-weight:600;
  font-size:.72rem; letter-spacing:.06em; text-transform:uppercase; }
div[data-testid="stMetricValue"]{ color:var(--ink);
  font-family:'Space Grotesk',sans-serif; font-weight:700; }

/* ---------- Tabs ---------- */
div[data-baseweb="tab-list"]{ gap:2px; border-bottom:1px solid var(--line); }
button[data-baseweb="tab"]{ font-weight:600; color:var(--muted); }
button[data-baseweb="tab"][aria-selected="true"]{ color:var(--green); }
div[data-baseweb="tab-highlight"]{ background:var(--green); height:3px; border-radius:3px; }

/* ---------- Buttons ---------- */
div.stButton > button{ border-radius:10px; font-weight:600; border:1px solid var(--line);
  transition:transform .05s ease, box-shadow .15s ease; }
div.stButton > button:hover{ box-shadow:var(--shadow); }
div.stButton > button:active{ transform:translateY(1px); }
div.stButton > button[kind="primary"]{
  background:linear-gradient(120deg,var(--green),var(--cyan-d));
  border:0; color:#fff; }
div.stButton > button[kind="primary"]:hover{
  filter:brightness(1.04); box-shadow:0 8px 20px rgba(6,182,212,.28); }
.stDownloadButton > button{ border-radius:10px; font-weight:600; }

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"]{ background:#FBFDFE; border-right:1px solid var(--line); }
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3{ color:var(--ink);
  font-size:1.02rem; padding-left:9px; border-left:3px solid var(--green); }
section[data-testid="stSidebar"] .stButton > button{ border-radius:9px; }

/* inputs */
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div{ border-radius:9px; }
div[data-testid="stDataFrame"]{ border-radius:10px; border:1px solid var(--line); overflow:hidden; }

/* alerts / dividers / captions */
div[data-testid="stNotification"], .stAlert{ border-radius:11px; }
hr{ border-color:var(--line); }
[data-testid="stCaptionContainer"]{ color:var(--muted); }

/* scrollbar */
::-webkit-scrollbar{ width:10px; height:10px; }
::-webkit-scrollbar-thumb{ background:#CBD8E2; border-radius:8px; border:2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover{ background:#AFC0CD; }

/* ---------- Mobile ---------- */
@media (max-width:640px){
  .block-container{ padding-top:1rem; padding-left:.7rem; padding-right:.7rem; }
  .ar-hero{ padding:16px 16px; border-radius:14px; }
  .ar-title{ font-size:1.3rem; }
  .ar-sub{ font-size:.64rem; letter-spacing:.12em; }
  .ar-chip{ margin-left:0; margin-top:6px; }
  .ar-logo{ height:40px; }
  div[data-testid="stMetricValue"]{ font-size:1.35rem; }
}
</style>
"""


@lru_cache(maxsize=1)
def _logo_data_uri():
    try:
        data = LOGO_PATH.read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode()
    except Exception:
        return None


def _hero():
    uri = _logo_data_uri()
    mark = (f"<img class='ar-logo' src='{uri}' alt='OneRoot'/>"
            if uri else "<div class='ar-mark'>\U0001F6F0</div>")
    st.markdown(
        f"""
        <div class="ar-hero">
          <div class="ar-hero-row">
            {mark}
            <div>
              <div class="ar-title">{APP_NAME.replace('OneRoot ', '')}</div>
              <div class="ar-sub">Satellite Crop Intelligence &nbsp;·&nbsp; OneRoot (ENP Farms)</div>
            </div>
            <div class="ar-chip"><span class="ar-dot"></span> LIVE · EARTH ENGINE</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def dashboard():

    st.markdown(_CSS, unsafe_allow_html=True)

    _hero()

    st.markdown(
        "<div class='ar-note'>\U0001F6F0 <b>Free open-source build</b> "
        "(Google Earth Engine) on a shared monthly compute budget — "
        "please test mindfully: one heavy layer at a time, reasonable "
        "radius, no rapid repeat clicks. Live usage is in the sidebar's "
        "<b>Service health</b> panel.</div>",
        unsafe_allow_html=True)

    # All controls live in the collapsible sidebar - on mobile it
    # folds into a hamburger menu and the map/results get full width.
    with st.sidebar:
        from ui.help import help_button
        help_button()
        sidebar()
        st.divider()
        layer_manager()
        st.divider()
        project_panel()
        st.divider()
        from core.usage import health_panel
        health_panel()

    mapview()

    st.divider()

    results()
