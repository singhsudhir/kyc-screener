from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime
from typing import Any

import httpx
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
API_URL = "http://localhost:8000"

RISK_CFG = {
    "Green": {"hex": "#22C55E", "glow": "rgba(34,197,94,0.25)",  "label": "LOW RISK",    "icon": "✓"},
    "Amber": {"hex": "#F59E0B", "glow": "rgba(245,158,11,0.25)", "label": "MEDIUM RISK",  "icon": "!"},
    "Red":   {"hex": "#EF4444", "glow": "rgba(239,68,68,0.25)",  "label": "HIGH RISK",    "icon": "✕"},
}

FACTOR_COLORS: dict[str, str] = {
    "Sanctions":     "#EF4444",
    "PEP":           "#F59E0B",
    "Adverse Media": "#F97316",
    "Jurisdiction":  "#A78BFA",
    "Industry":      "#60A5FA",
    "Ownership":     "#34D399",
}

AGENTS = [
    ("research",  "🔍", "Research Agent",    "Web search & public records"),
    ("sanctions", "⚖️", "Sanctions Check",   "OFAC · EU · UN · more"),
    ("ubo",       "🏢", "UBO Mapping",        "Beneficial ownership"),
    ("risk",      "📊", "Risk Assessment",    "AI-powered scoring"),
]

# Approximate cumulative time fractions for visual pacing (sum = 1.0)
AGENT_PACING = [0.30, 0.25, 0.30, 0.15]

JURISDICTIONS: dict[str, str] = {
    "AF": "Afghanistan",        "AL": "Albania",            "DZ": "Algeria",
    "AO": "Angola",             "AR": "Argentina",          "AU": "Australia",
    "AT": "Austria",            "AZ": "Azerbaijan",         "BS": "Bahamas",
    "BH": "Bahrain",            "BY": "Belarus",            "BE": "Belgium",
    "BZ": "Belize",             "BM": "Bermuda",            "BO": "Bolivia",
    "BR": "Brazil",             "BG": "Bulgaria",           "KH": "Cambodia",
    "CM": "Cameroon",           "CA": "Canada",             "KY": "Cayman Islands",
    "CL": "Chile",              "CN": "China",              "CO": "Colombia",
    "HR": "Croatia",            "CU": "Cuba",               "CY": "Cyprus",
    "CZ": "Czech Republic",     "CD": "DR Congo",           "DK": "Denmark",
    "DO": "Dominican Republic", "EC": "Ecuador",            "EG": "Egypt",
    "EE": "Estonia",            "ET": "Ethiopia",           "FI": "Finland",
    "FR": "France",             "GE": "Georgia",            "DE": "Germany",
    "GH": "Ghana",              "GI": "Gibraltar",          "GR": "Greece",
    "GG": "Guernsey",           "HK": "Hong Kong",          "HU": "Hungary",
    "IS": "Iceland",            "IN": "India",              "ID": "Indonesia",
    "IR": "Iran",               "IQ": "Iraq",               "IE": "Ireland",
    "IM": "Isle of Man",        "IL": "Israel",             "IT": "Italy",
    "JM": "Jamaica",            "JP": "Japan",              "JE": "Jersey",
    "JO": "Jordan",             "KZ": "Kazakhstan",         "KE": "Kenya",
    "KW": "Kuwait",             "LV": "Latvia",             "LB": "Lebanon",
    "LY": "Libya",              "LI": "Liechtenstein",      "LT": "Lithuania",
    "LU": "Luxembourg",         "MO": "Macau",              "MY": "Malaysia",
    "MV": "Maldives",           "MT": "Malta",              "MU": "Mauritius",
    "MX": "Mexico",             "MD": "Moldova",            "MC": "Monaco",
    "MN": "Mongolia",           "ME": "Montenegro",         "MA": "Morocco",
    "MM": "Myanmar",            "NL": "Netherlands",        "NZ": "New Zealand",
    "NG": "Nigeria",            "NO": "Norway",             "OM": "Oman",
    "PK": "Pakistan",           "PA": "Panama",             "PY": "Paraguay",
    "PE": "Peru",               "PH": "Philippines",        "PL": "Poland",
    "PT": "Portugal",           "QA": "Qatar",              "RO": "Romania",
    "RU": "Russia",             "SA": "Saudi Arabia",       "SN": "Senegal",
    "RS": "Serbia",             "SG": "Singapore",          "SK": "Slovakia",
    "SI": "Slovenia",           "SO": "Somalia",            "ZA": "South Africa",
    "ES": "Spain",              "LK": "Sri Lanka",          "SD": "Sudan",
    "SE": "Sweden",             "CH": "Switzerland",        "SY": "Syria",
    "TW": "Taiwan",             "TH": "Thailand",           "TN": "Tunisia",
    "TR": "Turkey",             "TM": "Turkmenistan",       "UG": "Uganda",
    "UA": "Ukraine",            "AE": "United Arab Emirates",
    "GB": "United Kingdom",     "US": "United States",      "UY": "Uruguay",
    "UZ": "Uzbekistan",         "VE": "Venezuela",          "VN": "Vietnam",
    "YE": "Yemen",              "ZM": "Zambia",             "ZW": "Zimbabwe",
}

_J_OPTIONS = sorted(f"{code} — {name}" for code, name in JURISDICTIONS.items())

# ─────────────────────────────────────────────────────────────────────────────
# Page config (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KYC Screener",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────────────────────
# CSS — dark enterprise design system
# ─────────────────────────────────────────────────────────────────────────────
def _css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Hide Streamlit chrome ───────────────────────────── */
#MainMenu          { visibility: hidden; }
footer             { visibility: hidden; }
header             { visibility: hidden; }
[data-testid="stDecoration"]   { display: none !important; }
[data-testid="stSidebarNav"]   { display: none !important; }
section[data-testid="stSidebar"] { display: none !important; }

/* ── Base ────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }

html, body, .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
    background: #0E1117 !important;
    color: #E6EDF3 !important;
}

:root {
    --bg:          #0E1117;
    --bg-card:     #161B22;
    --bg-card-alt: #1C2230;
    --bg-input:    #21262D;
    --border:      rgba(255,255,255,0.08);
    --border-med:  rgba(255,255,255,0.13);
    --text:        #E6EDF3;
    --text-muted:  #8B949E;
    --text-dim:    #4A5568;
    --blue:        #388BFD;
    --r:           8px;
    --shadow:      0 1px 2px rgba(0,0,0,0.3), 0 4px 16px rgba(0,0,0,0.4);
    --shadow-lg:   0 8px 24px rgba(0,0,0,0.5);
}

/* ── Layout container — max 800px centred ──────────── */
.block-container {
    max-width: 860px !important;
    margin: 0 auto !important;
    padding: 2rem 1.5rem 4rem !important;
}

/* ── Inputs (dark) ───────────────────────────────────── */
.stTextInput input,
.stSelectbox > div > div {
    background: var(--bg-input) !important;
    border: 1px solid var(--border-med) !important;
    border-radius: var(--r) !important;
    color: var(--text) !important;
    font-family: inherit !important;
    font-size: 0.875rem !important;
}
.stTextInput input::placeholder { color: var(--text-dim) !important; }
.stTextInput input:focus,
.stSelectbox > div > div:focus-within {
    border-color: var(--blue) !important;
    box-shadow: 0 0 0 3px rgba(56,139,253,0.2) !important;
    outline: none !important;
}

/* Selectbox dropdown styling */
.stSelectbox [data-baseweb="select"] > div {
    background: var(--bg-input) !important;
    border-color: var(--border-med) !important;
    border-radius: var(--r) !important;
}
.stSelectbox [data-baseweb="popover"] {
    background: #1C2230 !important;
    border: 1px solid var(--border-med) !important;
    border-radius: var(--r) !important;
}

/* Input labels */
.stTextInput label, .stSelectbox label {
    color: var(--text-muted) !important;
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}

/* ── Primary button ──────────────────────────────────── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #388BFD 0%, #1A65E0 100%) !important;
    color: #fff !important;
    border: none !important;
    border-radius: var(--r) !important;
    font-weight: 700 !important;
    font-size: 0.875rem !important;
    letter-spacing: 0.03em !important;
    padding: 0.6rem 1.5rem !important;
    width: 100% !important;
    transition: all 0.18s !important;
    box-shadow: 0 2px 8px rgba(56,139,253,0.35) !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(56,139,253,0.5) !important;
}
.stButton > button[kind="primary"]:disabled {
    background: #21262D !important;
    color: var(--text-dim) !important;
    box-shadow: none !important;
    transform: none !important;
}

/* Secondary buttons */
.stDownloadButton > button {
    background: #21262D !important;
    color: var(--text) !important;
    border: 1px solid var(--border-med) !important;
    border-radius: var(--r) !important;
    font-weight: 600 !important;
    font-size: 0.8rem !important;
    transition: all 0.15s !important;
}
.stDownloadButton > button:hover {
    background: #2D3748 !important;
    border-color: rgba(255,255,255,0.2) !important;
}

/* ── Align button with inputs in same row ────────────── */
div[data-testid="column"]:last-child > div > div > div > .stButton {
    margin-top: 1.85rem !important;
}

/* ── Expanders ───────────────────────────────────────── */
[data-testid="stExpander"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    box-shadow: var(--shadow) !important;
    margin-bottom: 0.75rem !important;
}
[data-testid="stExpander"] > details > summary {
    background: transparent !important;
    padding: 1rem 1.25rem !important;
    font-weight: 600 !important;
    color: var(--text) !important;
    font-size: 0.875rem !important;
}
[data-testid="stExpander"] > details > summary:hover { background: rgba(255,255,255,0.03) !important; }
[data-testid="stExpander"] > details[open] > summary { border-bottom: 1px solid var(--border) !important; }
[data-testid="stExpander"] > details > div { padding: 1.25rem !important; }

/* ── Tabs ────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tablist"] {
    background: var(--bg-card) !important;
    border-radius: var(--r) var(--r) 0 0 !important;
    border-bottom: 1px solid var(--border) !important;
    padding: 0.5rem 0.5rem 0 !important;
    gap: 0.15rem !important;
}
[data-testid="stTabs"] [role="tab"] {
    color: var(--text-muted) !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    border-radius: 6px 6px 0 0 !important;
    padding: 0.5rem 1rem !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: var(--blue) !important;
    background: rgba(56,139,253,0.1) !important;
    border-bottom: 2px solid var(--blue) !important;
}
[data-testid="stTabContent"] {
    background: var(--bg-card) !important;
    border-radius: 0 0 var(--r) var(--r) !important;
    border: 1px solid var(--border) !important;
    border-top: none !important;
    padding: 1.5rem !important;
}

/* ── Status widget ───────────────────────────────────── */
[data-testid="stStatus"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    color: var(--text) !important;
}
[data-testid="stStatus"] p { color: var(--text-muted) !important; font-size: 0.85rem !important; }

/* ── Misc ────────────────────────────────────────────── */
hr { border-color: var(--border) !important; }
.stMarkdown p { color: var(--text) !important; }
code { background: #1C2230 !important; color: #79C0FF !important; }

/* ── Stepper pulse animation ─────────────────────────── */
@keyframes pulse {
    0%,100% { box-shadow: 0 0 0 0 rgba(56,139,253,0.5); }
    50%      { box-shadow: 0 0 0 6px rgba(56,139,253,0); }
}
</style>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reusable HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

def _card(content: str, padding: str = "1.25rem 1.5rem", margin_bottom: str = "1rem") -> str:
    return (
        f'<div style="background:#161B22;border:1px solid rgba(255,255,255,0.08);'
        f'border-radius:8px;padding:{padding};margin-bottom:{margin_bottom};'
        f'box-shadow:0 1px 2px rgba(0,0,0,0.3),0 4px 16px rgba(0,0,0,0.4);">'
        f"{content}</div>"
    )


def _badge(text: str, color: str, bg_alpha: str = "22") -> str:
    return (
        f'<span style="background:{color}{bg_alpha};color:{color};'
        f'border:1px solid {color}55;border-radius:999px;'
        f'padding:0.18rem 0.65rem;font-size:0.68rem;font-weight:700;letter-spacing:0.08em;">'
        f"{text}</span>"
    )


def _th_style() -> str:
    return (
        "padding:0.6rem 0.9rem;text-align:left;font-size:0.65rem;font-weight:700;"
        "text-transform:uppercase;letter-spacing:0.08em;color:#8B949E;"
        "border-bottom:1px solid rgba(255,255,255,0.08);"
    )


def _td_style(bold: bool = False) -> str:
    weight = "600" if bold else "400"
    return (
        f"padding:0.65rem 0.9rem;border-bottom:1px solid rgba(255,255,255,0.05);"
        f"font-size:0.85rem;color:#E6EDF3;font-weight:{weight};"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Page header
# ─────────────────────────────────────────────────────────────────────────────

def _render_header() -> None:
    st.markdown(
        """
<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:2.25rem;padding-bottom:1.25rem;
border-bottom:1px solid rgba(255,255,255,0.08);">
    <div style="width:38px;height:38px;border-radius:10px;
    background:linear-gradient(135deg,#388BFD,#7C3AED);
    display:flex;align-items:center;justify-content:center;font-size:1.15rem;flex-shrink:0;">🔍</div>
    <div>
        <h1 style="color:#E6EDF3;font-size:1.25rem;font-weight:800;margin:0;letter-spacing:-0.02em;">
            KYC Screener
        </h1>
        <p style="color:#4A5568;font-size:0.72rem;font-weight:500;margin:0;letter-spacing:0.04em;text-transform:uppercase;">
            Multi-Agent Intelligence Platform
        </p>
    </div>
</div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Risk gauge
# ─────────────────────────────────────────────────────────────────────────────

def _render_risk_badge(report: dict) -> None:
    entity    = report.get("entity", {})
    risk      = report.get("risk_rating", {})
    level     = risk.get("level", "Green")
    score     = risk.get("score", 0)
    cfg       = RISK_CFG[level]
    color     = cfg["hex"]
    glow      = cfg["glow"]
    label     = cfg["label"]

    try:
        ts    = datetime.fromisoformat(report.get("timestamp","").replace("Z","+00:00"))
        ts_str = ts.strftime("%d %b %Y  ·  %H:%M UTC")
    except Exception:
        ts_str = report.get("timestamp","")[:16]

    r, cx, cy   = 70, 110, 110
    circ        = 2 * math.pi * r
    progress    = (score / 100) * circ
    remaining   = circ - progress
    offset      = circ / 4

    gauge_svg = f"""
<svg viewBox="0 0 220 220" width="220" height="220">
  <defs>
    <filter id="glow_{level}">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
  </defs>
  <!-- Track -->
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none"
    stroke="rgba(255,255,255,0.06)" stroke-width="12"/>
  <!-- Progress arc -->
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none"
    stroke="{color}" stroke-width="12" stroke-linecap="round"
    stroke-dasharray="{progress:.2f} {remaining:.2f}"
    stroke-dashoffset="{offset:.2f}"
    filter="url(#glow_{level})"/>
  <!-- Inner fill -->
  <circle cx="{cx}" cy="{cy}" r="55" fill="{glow}"/>
  <!-- Score -->
  <text x="{cx}" y="{cy - 10}" text-anchor="middle"
    font-family="Inter,sans-serif" font-size="42" font-weight="800" fill="{color}">{score}</text>
  <text x="{cx}" y="{cy + 14}" text-anchor="middle"
    font-family="Inter,sans-serif" font-size="10" font-weight="600" fill="{color}" opacity="0.6"
    letter-spacing="2">/ 100</text>
</svg>"""

    st.markdown(
        _card(f"""
<div style="text-align:center;">
    {gauge_svg}
    <div style="
        display:inline-flex;align-items:center;gap:0.4rem;
        background:{glow};border:1.5px solid {color}66;
        border-radius:999px;padding:0.4rem 1.1rem;
        font-size:0.72rem;font-weight:800;letter-spacing:0.12em;text-transform:uppercase;
        color:{color};margin-top:-0.5rem;margin-bottom:0.9rem;
    ">{cfg['icon']} &nbsp; {label}</div>
    <p style="color:#E6EDF3;font-size:1.05rem;font-weight:700;margin:0 0 0.2rem;letter-spacing:-0.01em;">
        {entity.get('name','—')}
    </p>
    <p style="color:#4A5568;font-size:0.72rem;margin:0;">{ts_str}</p>
</div>
        """, padding="1.5rem 1.25rem"),
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Agent stepper
# ─────────────────────────────────────────────────────────────────────────────

def _stepper_html(active_idx: int, elapsed: float, complete: bool = False) -> str:
    """Render a vertical stepper as compact single-line HTML (no indentation = no Markdown code-block mis-parse)."""
    rows = ""
    for i, (_, icon, name, desc) in enumerate(AGENTS):
        if complete or i < active_idx:
            dot_bg     = "rgba(34,197,94,0.12)"
            dot_border = "#22C55E"
            name_color = "#E6EDF3"
            s_icon     = "✅"
            timing     = '<span style="color:#4A5568;font-size:0.72rem;">done</span>'
            line_bg    = "#22C55E"
        elif i == active_idx:
            dot_bg     = "rgba(56,139,253,0.12)"
            dot_border = "#388BFD"
            name_color = "#388BFD"
            s_icon     = "🔄"
            timing     = f'<span style="color:#388BFD;font-size:0.72rem;">{elapsed:.1f}s</span>'
            line_bg    = "#21262D"
        else:
            dot_bg     = "#161B22"
            dot_border = "#4A5568"
            name_color = "#4A5568"
            s_icon     = "⬜"
            timing     = ""
            line_bg    = "#21262D"

        pulse = "animation:pulse 1.2s ease-in-out infinite;" if (i == active_idx and not complete) else ""

        dot  = (f'<div style="width:32px;height:32px;border-radius:50%;flex-shrink:0;'
                f'background:{dot_bg};border:1.5px solid {dot_border};'
                f'display:flex;align-items:center;justify-content:center;font-size:0.95rem;{pulse}">'
                f'{s_icon}</div>')
        text = (f'<div style="flex:1;min-width:0;">'
                f'<div style="display:flex;align-items:center;gap:0.5rem;">'
                f'<span style="font-size:0.875rem;font-weight:600;color:{name_color};">{icon} {name}</span>'
                f'{timing}</div>'
                f'<span style="font-size:0.72rem;color:#4A5568;">{desc}</span></div>')
        step = f'<div style="display:flex;align-items:center;gap:0.9rem;padding:0.5rem 0;">{dot}{text}</div>'
        line = (f'<div style="width:2px;height:22px;margin:2px auto;background:{line_bg};border-radius:1px;"></div>'
                if i < len(AGENTS) - 1 else "")
        rows += f'<div>{step}{line}</div>'

    label = '<p style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#4A5568;margin:0 0 0.75rem;">Agent Pipeline</p>'
    return _card(label + rows)


# ─────────────────────────────────────────────────────────────────────────────
# Results sections
# ─────────────────────────────────────────────────────────────────────────────

def _render_research(rf: dict) -> None:
    summary    = rf.get("summary", "—")
    directors  = rf.get("directors", [])
    adverse    = rf.get("adverse_media", [])
    sources    = rf.get("sources", [])
    inc_date   = rf.get("incorporation_date")
    count_str  = f"{len(adverse)} item{'s' if len(adverse) != 1 else ''}"
    badge_html = (
        _badge(f"⚠  {count_str}", "#F59E0B") if adverse else _badge("✓  No adverse media", "#22C55E")
    )

    with st.expander(f"🔍  Research Agent — Public Records  {badge_html}", expanded=True):
        # Summary card
        st.markdown(
            f'<div style="background:#1C2230;border-radius:6px;padding:1rem 1.1rem;margin-bottom:1rem;">'
            f'<p style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
            f'color:#4A5568;margin:0 0 0.4rem;">Summary</p>'
            f'<p style="font-size:0.875rem;color:#C9D1D9;line-height:1.75;margin:0;">{summary}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

        col_a, col_b = st.columns(2)

        with col_a:
            if directors:
                rows = "".join(
                    f'<tr><td style="{_td_style(bold=True)}">{d["name"]}</td>'
                    f'<td style="{_td_style()}">{d.get("role","Director")}</td>'
                    f'<td style="{_td_style()}">{d.get("nationality","—")}</td></tr>'
                    for d in directors
                )
                st.markdown(
                    f'<p style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#4A5568;margin:0 0 0.5rem;">Directors</p>'
                    f'<div style="overflow-x:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.07);">'
                    f'<table style="width:100%;border-collapse:collapse;">'
                    f'<thead><tr>'
                    f'<th style="{_th_style()}">Name</th>'
                    f'<th style="{_th_style()}">Role</th>'
                    f'<th style="{_th_style()}">Nationality</th>'
                    f'</tr></thead><tbody>{rows}</tbody></table></div>',
                    unsafe_allow_html=True,
                )
            if inc_date:
                st.markdown(
                    f'<p style="font-size:0.78rem;color:#4A5568;margin-top:0.75rem;">📅 Incorporated: <strong style="color:#8B949E;">{inc_date}</strong></p>',
                    unsafe_allow_html=True,
                )

        with col_b:
            if adverse:
                st.markdown(
                    '<p style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#4A5568;margin:0 0 0.5rem;">Adverse Media</p>',
                    unsafe_allow_html=True,
                )
                for item in adverse:
                    st.markdown(
                        f'<div style="display:flex;gap:0.6rem;background:rgba(245,158,11,0.08);'
                        f'border:1px solid rgba(245,158,11,0.2);border-radius:6px;'
                        f'padding:0.6rem 0.8rem;margin-bottom:0.5rem;">'
                        f'<span style="color:#F59E0B;flex-shrink:0;">⚠</span>'
                        f'<span style="font-size:0.8rem;color:#C9D1D9;line-height:1.5;">{item}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(
                    '<div style="display:flex;gap:0.5rem;align-items:center;background:rgba(34,197,94,0.08);'
                    'border:1px solid rgba(34,197,94,0.2);border-radius:6px;padding:0.75rem 1rem;">'
                    '<span style="color:#22C55E;">✓</span>'
                    '<span style="font-size:0.85rem;color:#C9D1D9;">No adverse media identified</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )

        if sources:
            with st.expander(f"Sources ({len(sources)})", expanded=False):
                for s in sources:
                    st.markdown(
                        f'<a href="{s}" target="_blank" style="font-size:0.78rem;color:#388BFD;word-break:break-all;">{s}</a><br>',
                        unsafe_allow_html=True,
                    )


def _render_sanctions(sr: dict) -> None:
    is_sanctioned = sr.get("is_sanctioned", False)
    hits          = sr.get("hits", [])
    lists         = sr.get("checked_lists", [])
    badge_html    = (
        _badge(f"✕  HIT FOUND  ({len(hits)})", "#EF4444") if is_sanctioned
        else _badge("✓  CLEAR", "#22C55E")
    )

    with st.expander(f"⚖️  Sanctions Screening  {badge_html}", expanded=True):
        color, bg_color, border_color, icon_str, msg = (
            ("#EF4444", "rgba(239,68,68,0.08)", "rgba(239,68,68,0.3)", "✕",
             f"SANCTIONED — matched on: {', '.join(lists)}")
            if is_sanctioned else
            ("#22C55E", "rgba(34,197,94,0.08)", "rgba(34,197,94,0.3)", "✓",
             f"No matches above threshold — {len(lists)} list{'s' if len(lists) != 1 else ''} screened")
        )
        st.markdown(
            f'<div style="display:flex;gap:0.75rem;align-items:center;background:{bg_color};'
            f'border:1px solid {border_color};border-radius:6px;padding:0.85rem 1rem;margin-bottom:1rem;">'
            f'<span style="color:{color};font-size:1rem;font-weight:800;">{icon_str}</span>'
            f'<span style="font-size:0.875rem;font-weight:600;color:{color};">{msg}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if hits:
            rows = ""
            for h in hits:
                pct   = int(h["match_score"] * 100)
                sc    = "#EF4444" if pct >= 85 else "#F59E0B" if pct >= 60 else "#8B949E"
                rows += (
                    f'<tr>'
                    f'<td style="{_td_style(bold=True)}">{h["matched_name"]}</td>'
                    f'<td style="{_td_style()}">'
                    f'<span style="background:rgba(239,68,68,0.12);color:#EF4444;border-radius:4px;'
                    f'padding:0.15rem 0.5rem;font-size:0.68rem;font-weight:700;">{h["list_name"]}</span>'
                    f'</td>'
                    f'<td style="{_td_style()}">'
                    f'<div style="display:flex;align-items:center;gap:0.5rem;">'
                    f'<div style="flex:1;background:rgba(255,255,255,0.07);border-radius:999px;height:5px;min-width:60px;">'
                    f'<div style="width:{pct}%;height:5px;background:{sc};border-radius:999px;"></div></div>'
                    f'<span style="font-size:0.75rem;font-weight:700;color:{sc};min-width:32px;">{pct}%</span>'
                    f'</div></td>'
                    f'<td style="{_td_style()}">{h.get("entity_type","—")}</td>'
                    f'<td style="{_td_style()}">{h.get("listing_date","—")}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<div style="overflow-x:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.07);">'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<thead><tr>'
                f'<th style="{_th_style()}">Matched Name</th>'
                f'<th style="{_th_style()}">List</th>'
                f'<th style="{_th_style()}">Score</th>'
                f'<th style="{_th_style()}">Type</th>'
                f'<th style="{_th_style()}">Listing Date</th>'
                f'</tr></thead><tbody>{rows}</tbody></table></div>',
                unsafe_allow_html=True,
            )


def _render_ubo(ubo: dict) -> None:
    ubos     = ubo.get("ubos", [])
    verified = ubo.get("ownership_verified", False)
    notes    = ubo.get("notes", "")
    pep_ct   = sum(1 for u in ubos if u.get("pep_status"))
    badge_html = (
        _badge(f"⚠  {pep_ct} PEP", "#EF4444") if pep_ct
        else (_badge(f"✓  {len(ubos)} UBO{'s' if len(ubos) != 1 else ''}", "#22C55E") if ubos
              else _badge("No Data", "#8B949E"))
    )

    with st.expander(f"🏢  UBO Structure  {badge_html}", expanded=True):
        if not verified:
            st.markdown(
                '<div style="display:flex;gap:0.5rem;background:rgba(245,158,11,0.08);'
                'border:1px solid rgba(245,158,11,0.2);border-radius:6px;'
                'padding:0.7rem 1rem;margin-bottom:1rem;">'
                '<span style="color:#F59E0B;">⚠</span>'
                '<span style="font-size:0.82rem;color:#C9D1D9;">Ownership structure could not be fully verified.</span>'
                '</div>',
                unsafe_allow_html=True,
            )

        if not ubos:
            st.markdown(
                '<p style="color:#4A5568;font-size:0.875rem;text-align:center;padding:1.5rem;">No UBO records identified</p>',
                unsafe_allow_html=True,
            )
        else:
            # Simple ownership hierarchy
            for u in ubos:
                pep    = u.get("pep_status", False)
                pct    = u.get("ownership_percentage")
                pct_w  = min(int(pct), 100) if pct else 0
                pct_s  = f"{pct:.1f}%" if pct is not None else "—"
                color  = "#EF4444" if pep else "#22C55E"
                via    = ", ".join(u.get("intermediate_entities", []))

                via_html = (
                    '<br><span style="font-size:0.72rem;color:#4A5568;">via ' + via + '</span>'
                    if via else ""
                )
                pep_badge = (
                    '<span style="background:rgba(239,68,68,0.12);color:#EF4444;border-radius:999px;'
                    'padding:0.15rem 0.6rem;font-size:0.68rem;font-weight:700;">⚠ PEP</span>'
                    if pep else
                    '<span style="background:rgba(34,197,94,0.1);color:#22C55E;border-radius:999px;'
                    'padding:0.15rem 0.6rem;font-size:0.68rem;font-weight:700;">✓ Clear</span>'
                )
                ubo_nat = u.get("nationality", "—")
                st.markdown(
                    f'<div style="border-left:2px solid {color};padding-left:0.85rem;margin-bottom:0.85rem;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.35rem;">'
                    f'<div>'
                    f'<span style="font-size:0.875rem;font-weight:600;color:#E6EDF3;">{u["name"]}</span>'
                    f'{via_html}'
                    f'</div>'
                    f'<div style="display:flex;align-items:center;gap:0.5rem;">'
                    f'{pep_badge}'
                    f'<span style="font-size:0.8rem;font-weight:700;color:#8B949E;">{pct_s}</span>'
                    f'</div></div>'
                    f'<div style="display:flex;align-items:center;gap:0.6rem;">'
                    f'<div style="flex:1;background:rgba(255,255,255,0.06);border-radius:999px;height:4px;">'
                    f'<div style="width:{pct_w}%;height:4px;background:{color};border-radius:999px;"></div></div>'
                    f'<span style="font-size:0.7rem;color:#4A5568;min-width:40px;">{ubo_nat}</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

        if notes:
            st.markdown(
                f'<p style="font-size:0.8rem;color:#4A5568;background:#1C2230;'
                f'border-radius:6px;padding:0.75rem;margin-top:0.5rem;">{notes}</p>',
                unsafe_allow_html=True,
            )


def _render_risk_factors(risk: dict) -> None:
    factors = risk.get("factors", [])
    summary = risk.get("summary", "—")
    level   = risk.get("level", "Green")
    score   = risk.get("score", 0)
    cfg     = RISK_CFG[level]
    badge_html = _badge(f"{cfg['icon']}  {cfg['label']}  ·  {score}/100", cfg["hex"])

    with st.expander(f"📊  Risk Assessment  {badge_html}", expanded=True):
        st.markdown(
            f'<div style="background:#1C2230;border-radius:6px;padding:1rem 1.1rem;margin-bottom:1.25rem;">'
            f'<p style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
            f'color:#4A5568;margin:0 0 0.4rem;">Analyst Assessment</p>'
            f'<p style="font-size:0.875rem;color:#C9D1D9;line-height:1.75;margin:0;">{summary}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if factors:
            st.markdown(
                '<p style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
                'letter-spacing:0.08em;color:#4A5568;margin:0 0 0.75rem;">Factor Breakdown</p>',
                unsafe_allow_html=True,
            )
            for f in sorted(factors, key=lambda x: x["weight"], reverse=True):
                cat   = f["category"]
                color = FACTOR_COLORS.get(cat, "#8B949E")
                pct   = int(f["weight"] * 100)
                st.markdown(
                    f'<div style="margin-bottom:0.9rem;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.35rem;">'
                    f'<div style="display:flex;align-items:center;gap:0.5rem;">'
                    f'<span style="background:{color}22;color:{color};border-radius:4px;'
                    f'padding:0.12rem 0.45rem;font-size:0.65rem;font-weight:700;letter-spacing:0.06em;">{cat}</span>'
                    f'<span style="font-size:0.8rem;color:#8B949E;">{f["description"]}</span>'
                    f'</div>'
                    f'<span style="font-size:0.75rem;font-weight:700;color:{color};margin-left:0.5rem;">{pct}%</span>'
                    f'</div>'
                    f'<div style="background:rgba(255,255,255,0.06);border-radius:999px;height:7px;">'
                    f'<div style="width:{pct}%;height:7px;background:linear-gradient(90deg,{color}66,{color});'
                    f'border-radius:999px;"></div></div></div>',
                    unsafe_allow_html=True,
                )


# ─────────────────────────────────────────────────────────────────────────────
# Export section
# ─────────────────────────────────────────────────────────────────────────────

def _build_markdown(report: dict) -> str:
    e   = report.get("entity", {})
    rr  = report.get("risk_rating", {})
    rf  = report.get("research_findings", {})
    sr  = report.get("sanctions_results", {})
    ubo = report.get("ubo_structure", {})
    ts  = report.get("timestamp", "")[:10]

    ubos_md = "\n".join(
        f"- **{u['name']}** — {u.get('ownership_percentage','?')}% "
        f"({u.get('nationality','—')}) {'[⚠ PEP]' if u.get('pep_status') else ''}"
        for u in ubo.get("ubos", [])
    ) or "_No UBO records identified_"

    adverse_md = "\n".join(f"- {a}" for a in rf.get("adverse_media", [])) or "_None identified_"
    sanctions_md = (
        f"**SANCTIONED** — matched on: {', '.join(sr.get('checked_lists',[]))}"
        if sr.get("is_sanctioned") else
        f"**CLEAR** — {len(sr.get('checked_lists',[]))} lists screened"
    )

    return f"""# KYC Screening Report: {e.get('name','—')}

**Date:** {ts}
**Jurisdiction:** {e.get('jurisdiction','—')}
**Registration:** {e.get('registration_number','—')}
**Risk Rating:** {rr.get('level','—')} (Score: {rr.get('score',0)}/100)

---

## Risk Summary

{rr.get('summary','—')}

---

## Research Findings

{rf.get('summary','—')}

### Adverse Media

{adverse_md}

---

## Sanctions Screening

{sanctions_md}

---

## Beneficial Ownership

{ubos_md}

---

_Generated by KYC Intelligence Platform · {ts}_
"""


def _render_export(report: dict) -> None:
    entity    = report.get("entity", {})
    name_slug = entity.get("name", "report").replace(" ", "_")
    ts_slug   = report.get("timestamp", "")[:10]

    st.markdown(
        _card(
            '<p style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
            'color:#4A5568;margin:0 0 1rem;">Export Report</p>',
            padding="1.25rem 1.5rem 0.75rem",
        ),
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "📄  Download Markdown",
            data=_build_markdown(report),
            file_name=f"KYC_{name_slug}_{ts_slug}.md",
            mime="text/markdown",
        )
    with c2:
        st.download_button(
            "📦  Download JSON",
            data=json.dumps(report, indent=2, default=str),
            file_name=f"KYC_{name_slug}_{ts_slug}.json",
            mime="application/json",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Full report renderer
# ─────────────────────────────────────────────────────────────────────────────

def _render_report(report: dict) -> None:
    st.session_state["last_report"] = report

    entity    = report.get("entity", {})
    risk      = report.get("risk_rating", {})
    research  = report.get("research_findings", {})
    sanctions = report.get("sanctions_results", {})
    ubo       = report.get("ubo_structure", {})
    flags     = report.get("flags", [])
    elapsed   = st.session_state.get("screening_elapsed", 30.0)

    # Risk badge + completed stepper side by side
    col_gauge, col_stepper = st.columns([2, 3], gap="medium")
    with col_gauge:
        _render_risk_badge(report)
    with col_stepper:
        st.markdown(_stepper_html(0, elapsed, complete=True), unsafe_allow_html=True)

    # Flags
    if flags:
        items = "".join(
            f'<div style="display:flex;gap:0.6rem;padding:0.5rem 0;'
            f'border-bottom:1px solid rgba(239,68,68,0.15);">'
            f'<span style="color:#EF4444;font-weight:800;flex-shrink:0;">⚠</span>'
            f'<span style="font-size:0.85rem;color:#FCA5A5;">{f}</span></div>'
            for f in flags
        )
        st.markdown(
            _card(
                f'<p style="font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;'
                f'color:#EF4444;margin:0 0 0.4rem;">⚠ Compliance Flags — Requires Senior Review</p>{items}',
                padding="1rem 1.25rem",
            ),
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)

    # Agent result cards
    _render_research(research)
    _render_sanctions(sanctions)
    _render_ubo(ubo)
    _render_risk_factors(risk)

    st.markdown("<div style='height:0.75rem;'></div>", unsafe_allow_html=True)
    _render_export(report)


# ─────────────────────────────────────────────────────────────────────────────
# Empty state
# ─────────────────────────────────────────────────────────────────────────────

def _render_empty() -> None:
    features = [
        ("🔍", "Research Agent",   "Searches the web and public registries for company background"),
        ("⚖️", "Sanctions Check",  "Screens against OFAC, EU, UN and OpenSanctions global lists"),
        ("🏢", "UBO Mapping",       "Maps the full beneficial ownership chain and flags PEPs"),
        ("📊", "Risk Assessment",   "Gemini 2.5 Pro assigns a calibrated Green / Amber / Red rating"),
    ]
    cards = "".join(
        f'<div style="background:#161B22;border:1px solid rgba(255,255,255,0.07);border-radius:8px;'
        f'padding:1.1rem 1.25rem;flex:1;min-width:160px;">'
        f'<div style="font-size:1.4rem;margin-bottom:0.5rem;">{icon}</div>'
        f'<p style="font-size:0.8rem;font-weight:700;color:#E6EDF3;margin:0 0 0.25rem;">{title}</p>'
        f'<p style="font-size:0.72rem;color:#4A5568;margin:0;line-height:1.5;">{desc}</p>'
        f'</div>'
        for icon, title, desc in features
    )
    st.markdown(
        f'<div style="text-align:center;padding:3rem 0 2rem;">'
        f'<p style="color:#4A5568;font-size:0.875rem;margin:0 0 2rem;line-height:1.7;">'
        f'Enter a company name and jurisdiction above, then click <strong style="color:#8B949E;">Screen Company</strong>.</p>'
        f'<div style="display:flex;gap:0.75rem;flex-wrap:wrap;">{cards}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Animated stepper while API call runs (threading)
# ─────────────────────────────────────────────────────────────────────────────

def _run_screening(payload: dict) -> None:
    """Start API call in a thread and animate the stepper while waiting."""
    result: dict[str, Any] = {}

    def _call() -> None:
        try:
            with httpx.Client(timeout=180) as client:
                r = client.post(f"{API_URL}/screen", json=payload)
            r.raise_for_status()
            result["report"] = r.json()
        except httpx.HTTPStatusError as e:
            result["error"] = f"API error {e.response.status_code}: {e.response.text}"
        except Exception as e:
            result["error"] = str(e)

    thread    = threading.Thread(target=_call, daemon=True)
    t_start   = time.time()
    thread.start()

    stepper_ph = st.empty()
    cumulative = [sum(AGENT_PACING[:i]) for i in range(len(AGENT_PACING))]

    while thread.is_alive():
        elapsed = time.time() - t_start
        # Determine which agent step appears active based on pacing
        frac    = min(elapsed / max(elapsed + 1, 60), 0.99)
        active  = next(
            (i for i in range(len(AGENT_PACING) - 1, -1, -1) if frac >= cumulative[i]),
            0,
        )
        stepper_ph.markdown(_stepper_html(active, elapsed), unsafe_allow_html=True)
        time.sleep(0.4)

    thread.join()
    elapsed = time.time() - t_start
    stepper_ph.empty()

    if "error" in result:
        st.error(f"Screening failed: {result['error']}")
        return

    st.session_state["last_report"]      = result["report"]
    st.session_state["screening_elapsed"] = elapsed
    history = st.session_state.get("history", [])
    history.append(result["report"])
    st.session_state["history"] = history[-8:]
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
_css()
_render_header()

# ── Input row (single line) ───────────────────────────────────────────────────
c_name, c_jur, c_btn = st.columns([5, 3, 2])
with c_name:
    company_name = st.text_input(
        "Company Name",
        placeholder="Acme Corp Ltd",
        label_visibility="visible",
    )
with c_jur:
    jur_option = st.selectbox(
        "Jurisdiction",
        options=[""] + _J_OPTIONS,
        index=0,
        format_func=lambda x: x or "Select…",
    )
with c_btn:
    submitted = st.button(
        "Screen Company ▶",
        type="primary",
        use_container_width=True,
    )

st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)

# ── Dispatch ──────────────────────────────────────────────────────────────────
if submitted:
    if not company_name:
        st.error("Please enter a company name.")
    elif not jur_option:
        st.error("Please select a jurisdiction.")
    else:
        jurisdiction = jur_option.split(" — ")[0].strip()
        _run_screening({
            "name":        company_name,
            "jurisdiction": jurisdiction,
        })

elif "last_report" in st.session_state:
    _render_report(st.session_state["last_report"])

else:
    _render_empty()

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    """
<div style="
    margin-top:3rem;padding-top:1.25rem;
    border-top:1px solid rgba(255,255,255,0.06);
    display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;
">
    <span style="color:#4A5568;font-size:0.72rem;">
        ⚠ For compliance screening purposes only. Not legal advice. Always verify findings independently.
    </span>
    <span style="color:#4A5568;font-size:0.72rem;">
        Powered by &nbsp;
        <strong style="color:#8B949E;">Gemini 2.5 Pro</strong> ·
        <strong style="color:#8B949E;">LangGraph</strong> ·
        <strong style="color:#8B949E;">OpenSanctions</strong>
    </span>
</div>
    """,
    unsafe_allow_html=True,
)
