from __future__ import annotations

import copy
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
# Demo mode — hardcoded scenarios (no API calls)
# ─────────────────────────────────────────────────────────────────────────────
DEMO_SCENARIOS: list[tuple[str, str, str]] = [
    ("clean_corp",     "Clean Corp BV",      "🟢  GREEN  · Score 15"),
    ("global_trading", "Global Trading Ltd", "🟡  AMBER  · Score 55"),
    ("shadow_finance", "Shadow Finance SA",  "🔴  RED    · Score 92"),
]

_TS = "2026-05-21T10:00:00Z"

MOCK_REPORTS: dict[str, dict] = {
    "clean_corp": {
        "entity": {
            "name": "Clean Corp BV",
            "jurisdiction": "NL",
            "registration_number": "KVK-87654321",
            "address": "Keizersgracht 123, 1015 CJ Amsterdam, Netherlands",
            "website": "https://cleancorp.nl",
            "industry": "Logistics & Supply Chain",
        },
        "risk_rating": {
            "level": "Green",
            "score": 15,
            "summary": (
                "Clean Corp BV presents a low-risk profile. The company is a well-established Dutch "
                "logistics firm with transparent ownership, no adverse media, and no sanctions exposure. "
                "The sole beneficial owner is a Netherlands national with no PEP associations. "
                "Standard onboarding is appropriate."
            ),
            "factors": [
                {"category": "Sanctions",     "weight": 0.00, "description": "No sanctions exposure identified"},
                {"category": "PEP",           "weight": 0.05, "description": "No PEP associations"},
                {"category": "Adverse Media", "weight": 0.08, "description": "No adverse media found"},
                {"category": "Jurisdiction",  "weight": 0.12, "description": "Netherlands — low-risk FATF member"},
                {"category": "Industry",      "weight": 0.10, "description": "Logistics — standard risk sector"},
                {"category": "Ownership",     "weight": 0.05, "description": "Simple, transparent 100% ownership"},
            ],
        },
        "research_findings": {
            "summary": (
                "Clean Corp BV is a Dutch logistics and supply chain company founded in April 2015, "
                "headquartered in Amsterdam. The company employs approximately 45 staff and operates "
                "primarily across the Benelux region. Public records show consistent trading activity "
                "with no regulatory issues or adverse findings."
            ),
            "directors": [
                {"name": "Jan de Vries",    "role": "Director / UBO", "nationality": "NL", "date_of_birth": "1975-03-12"},
                {"name": "Marta Kowalski",  "role": "CFO",            "nationality": "NL", "date_of_birth": "1980-07-22"},
            ],
            "adverse_media": [],
            "sources": [
                "https://www.kvk.nl/cleancorp-bv",
                "https://opencorporates.com/companies/nl/87654321",
                "https://gleif.org/lei/clean-corp-bv",
            ],
            "incorporation_date": "2015-04-18",
        },
        "sanctions_results": {
            "is_sanctioned": False,
            "hits": [],
            "checked_lists": ["OFAC SDN", "EU Consolidated", "UN Security Council", "UK HMT", "OpenSanctions Global"],
        },
        "ubo_structure": {
            "ubos": [
                {
                    "name": "Jan de Vries",
                    "ownership_percentage": 100.0,
                    "nationality": "NL",
                    "pep_status": False,
                    "intermediate_entities": [],
                }
            ],
            "ownership_verified": True,
            "notes": "Sole beneficial owner confirmed via Dutch Chamber of Commerce (KVK) registry records.",
        },
        "flags": [],
        "timestamp": _TS,
    },

    "global_trading": {
        "entity": {
            "name": "Global Trading Ltd",
            "jurisdiction": "GB",
            "registration_number": "UK-12345678",
            "address": "1 Canary Wharf, London E14 5AB, United Kingdom",
            "website": "https://globaltrading.co.uk",
            "industry": "Import / Export Trading",
        },
        "risk_rating": {
            "level": "Amber",
            "score": 55,
            "summary": (
                "Global Trading Ltd presents a medium-risk profile. While no direct sanctions exposure "
                "exists, the company was subject to a UK HMRC transfer-pricing investigation (settled 2022 "
                "for GBP 1.2 M) and 70 % of its equity is held via a Cyprus-registered holding company "
                "whose ultimate beneficial owners could not be confirmed from public records. Enhanced due "
                "diligence is recommended before onboarding."
            ),
            "factors": [
                {"category": "Sanctions",     "weight": 0.00, "description": "No direct sanctions exposure"},
                {"category": "PEP",           "weight": 0.10, "description": "No confirmed PEPs; one director under review"},
                {"category": "Adverse Media", "weight": 0.45, "description": "HMRC tax dispute (2021), settled 2022"},
                {"category": "Jurisdiction",  "weight": 0.30, "description": "UK entity with Cyprus intermediate — mixed risk"},
                {"category": "Industry",      "weight": 0.30, "description": "Import/export — elevated inherent risk"},
                {"category": "Ownership",     "weight": 0.55, "description": "Indirect 70% via Cyprus holding — UBO unconfirmed"},
            ],
        },
        "research_findings": {
            "summary": (
                "Global Trading Ltd is a UK-registered import/export firm established in 2010. "
                "In 2021, HMRC launched a transfer-pricing investigation into the company, settled in "
                "2022 with a GBP 1.2 M adjustment. The company trades primarily in commodities across "
                "Europe and Southeast Asia. A Cyprus director, Nikolaos Papadopoulos, sits on the board "
                "of the parent holding entity."
            ),
            "directors": [
                {"name": "Alexander Hughes",       "role": "Managing Director", "nationality": "GB", "date_of_birth": "1968-11-30"},
                {"name": "Nikolaos Papadopoulos",  "role": "Director",          "nationality": "CY", "date_of_birth": "1972-05-14"},
            ],
            "adverse_media": [
                "HMRC launched transfer-pricing investigation into Global Trading Ltd (2021). Settled for GBP 1.2 M in 2022.",
                "Company named in Financial Times article on opaque UK-Cyprus ownership structures (Oct 2022).",
            ],
            "sources": [
                "https://find-and-update.company-information.service.gov.uk/company/UK12345678",
                "https://ft.com/content/2022/cyprus-structures-uk-firms",
            ],
            "incorporation_date": "2010-09-05",
        },
        "sanctions_results": {
            "is_sanctioned": False,
            "hits": [],
            "checked_lists": ["OFAC SDN", "EU Consolidated", "UN Security Council", "UK HMT", "OpenSanctions Global"],
        },
        "ubo_structure": {
            "ubos": [
                {
                    "name": "Alexander Hughes",
                    "ownership_percentage": 30.0,
                    "nationality": "GB",
                    "pep_status": False,
                    "intermediate_entities": [],
                },
                {
                    "name": "Meridian Holdings Ltd",
                    "ownership_percentage": 70.0,
                    "nationality": "CY",
                    "pep_status": False,
                    "intermediate_entities": ["Meridian Holdings Ltd (CY)"],
                },
            ],
            "ownership_verified": False,
            "notes": (
                "70 % ownership held via Meridian Holdings Ltd (Cyprus). Ultimate beneficial owner(s) "
                "of the Cyprus entity could not be confirmed from public records. Certificate of "
                "incumbency requested but not yet received."
            ),
        },
        "flags": [
            "COMPLEX OWNERSHIP: Indirect 70 % via Cyprus jurisdiction — UBO verification incomplete",
        ],
        "timestamp": _TS,
    },

    "shadow_finance": {
        "entity": {
            "name": "Shadow Finance SA",
            "jurisdiction": "PA",
            "registration_number": "PA-2019-4471892",
            "address": "Calle 50, Torre Global Bank, Panama City, Panama",
            "website": None,
            "industry": "Financial Services",
        },
        "risk_rating": {
            "level": "Red",
            "score": 92,
            "summary": (
                "Shadow Finance SA presents an extremely high-risk profile. The entity is "
                "Panama-registered with minimal public information and faces multiple fraud allegations. "
                "Director Dmitri Volkov has matched on the EU Consolidated Sanctions List at 87 % "
                "confidence. Beneficial ownership flows through four jurisdictions (PA→LV→CH→BVI) and "
                "could not be determined. Onboarding is strongly contraindicated."
            ),
            "factors": [
                {"category": "Sanctions",     "weight": 0.90, "description": "Director Dmitri Volkov matched on EU sanctions list"},
                {"category": "PEP",           "weight": 0.70, "description": "Director with suspected political connections"},
                {"category": "Adverse Media", "weight": 0.85, "description": "Fraud allegations, OCCRP report, regulatory flags"},
                {"category": "Jurisdiction",  "weight": 0.80, "description": "Panama — FATF grey-list jurisdiction"},
                {"category": "Industry",      "weight": 0.60, "description": "Financial services — high inherent risk"},
                {"category": "Ownership",     "weight": 0.95, "description": "4-layer PA→LV→CH→BVI structure; UBO unidentifiable"},
            ],
        },
        "research_findings": {
            "summary": (
                "Shadow Finance SA is a Panama-registered financial services entity incorporated in "
                "November 2019. Public information is extremely limited; no verified business operations "
                "could be independently confirmed. The company has been referenced in Panamanian court "
                "records in connection with alleged wire fraud and money laundering. Director Dmitri "
                "Volkov was named in an OCCRP report on organised shell-company networks (2023)."
            ),
            "directors": [
                {"name": "Dmitri Volkov",       "role": "Director",         "nationality": "RU", "date_of_birth": "1964-02-28"},
                {"name": "Carlos Mendez-Rios",  "role": "Registered Agent", "nationality": "PA", "date_of_birth": "1971-08-15"},
            ],
            "adverse_media": [
                "Shadow Finance SA referenced in Panama court proceedings for alleged wire fraud (2022).",
                "Director Dmitri Volkov named in OCCRP Organised Crime report on shell company networks (2023).",
                "Panamanian Superintendency of Banks flagged entity for suspicious transaction patterns (2023).",
                "Financial Intelligence Unit (UAF) Panama issued advisory notice regarding the entity (2024).",
            ],
            "sources": [
                "https://www.occrp.org/en/investigations/shadow-finance-networks-2023",
                "https://offshoreleaks.icij.org/nodes/shadow-finance-sa",
            ],
            "incorporation_date": "2019-11-03",
        },
        "sanctions_results": {
            "is_sanctioned": True,
            "hits": [
                {
                    "matched_name": "Dmitri Alexandrovich Volkov",
                    "list_name": "EU Consolidated Sanctions",
                    "match_score": 0.87,
                    "entity_type": "Individual",
                    "listing_date": "2022-03-15",
                    "details": "Listed for actions undermining the financial stability of EU member states.",
                }
            ],
            "checked_lists": ["OFAC SDN", "EU Consolidated", "UN Security Council", "UK HMT", "OpenSanctions Global"],
        },
        "ubo_structure": {
            "ubos": [
                {
                    "name": "Baltica Investments SIA",
                    "ownership_percentage": 100.0,
                    "nationality": "LV",
                    "pep_status": False,
                    "intermediate_entities": ["Baltica Investments SIA (LV)", "TrustCo AG (CH)", "Meridian Corp (BVI)"],
                }
            ],
            "ownership_verified": False,
            "notes": (
                "Ownership chain: Shadow Finance SA (PA) → Baltica Investments SIA (LV) → TrustCo AG "
                "(CH) → Meridian Corp (BVI) → ultimate beneficial owner(s) unknown. Four-layer "
                "cross-jurisdictional structure with nominee director arrangement suspected."
            ),
        },
        "flags": [
            "SANCTIONS HIT: Director Dmitri Volkov matched on EU Consolidated Sanctions List (87 % confidence)",
            "HIGH-RISK JURISDICTION: Panama — FATF monitored jurisdiction",
            "COMPLEX OWNERSHIP: 4-layer structure PA → LV → CH → BVI — UBO unidentifiable",
            "ADVERSE MEDIA: Fraud allegations, OCCRP report, multiple regulatory flags",
        ],
        "timestamp": _TS,
    },
}

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

def _section_label(text: str) -> None:
    st.markdown(f'<p style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.09em;color:#4A5568;margin:0.85rem 0 0.45rem;">{text}</p>', unsafe_allow_html=True)


def _render_research(rf: dict, entity: dict) -> None:
    summary   = rf.get("summary", "—")
    directors = rf.get("directors", [])
    adverse   = rf.get("adverse_media", [])
    sources   = rf.get("sources", [])
    inc_date  = rf.get("incorporation_date")
    adv_count  = len(adverse)
    status_txt = f"⚠  {adv_count} Flag{'s' if adv_count != 1 else ''}" if adverse else "✓  Clean"

    with st.expander(f"🔍  Research Agent — Public Records   {status_txt}", expanded=True):
        # ── Company overview ──────────────────────────────────────
        st.markdown(f'<div style="background:#1C2230;border-radius:6px;padding:1rem 1.1rem;margin-bottom:0.75rem;"><p style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.09em;color:#4A5568;margin:0 0 0.4rem;">Company Overview</p><p style="font-size:0.875rem;color:#C9D1D9;line-height:1.8;margin:0;">{summary}</p></div>', unsafe_allow_html=True)

        # ── Key facts table ───────────────────────────────────────
        _section_label("Key Facts")
        facts = [
            ("Jurisdiction", entity.get("jurisdiction", "—")),
            ("Incorporated", inc_date or "—"),
            ("Registration No.", entity.get("registration_number") or "—"),
            ("Industry", entity.get("industry") or "—"),
            ("Address", entity.get("address") or "—"),
            ("Website", entity.get("website") or "—"),
        ]
        fact_cells = "".join(
            f'<tr><td style="padding:0.5rem 0.9rem;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.72rem;font-weight:600;color:#4A5568;white-space:nowrap;">{k}</td><td style="padding:0.5rem 0.9rem;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.82rem;color:#C9D1D9;">{v}</td></tr>'
            for k, v in facts if v != "—"
        )
        st.markdown(f'<div style="overflow-x:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.07);margin-bottom:0.75rem;"><table style="width:100%;border-collapse:collapse;">{fact_cells}</table></div>', unsafe_allow_html=True)

        # ── Key personnel ─────────────────────────────────────────
        if directors:
            _section_label(f"Key Personnel ({len(directors)})")
            rows = "".join(
                f'<tr><td style="{_td_style(bold=True)}">{d.get("name","—")}</td><td style="{_td_style()}">{d.get("role","Director")}</td><td style="{_td_style()}">{d.get("nationality","—")}</td><td style="{_td_style()}">{d.get("date_of_birth","—")}</td></tr>'
                for d in directors
            )
            st.markdown(
                f'<div style="overflow-x:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.07);margin-bottom:0.75rem;"><table style="width:100%;border-collapse:collapse;"><thead><tr><th style="{_th_style()}">Name</th><th style="{_th_style()}">Role</th><th style="{_th_style()}">Nationality</th><th style="{_th_style()}">DOB</th></tr></thead><tbody>{rows}</tbody></table></div>',
                unsafe_allow_html=True,
            )

        # ── Red flags / adverse media ─────────────────────────────
        if adverse:
            _section_label(f"⚠ Red Flags & Adverse Media ({adv_count})")
            items_html = "".join(
                f'<div style="display:flex;gap:0.6rem;background:rgba(239,68,68,0.07);border:1px solid rgba(239,68,68,0.2);border-radius:6px;padding:0.65rem 0.9rem;margin-bottom:0.4rem;"><span style="color:#EF4444;flex-shrink:0;font-weight:700;">⚠</span><span style="font-size:0.82rem;color:#FCA5A5;line-height:1.55;">{item}</span></div>'
                for item in adverse
            )
            st.markdown(items_html, unsafe_allow_html=True)
        else:
            st.markdown('<div style="display:flex;gap:0.5rem;align-items:center;background:rgba(34,197,94,0.07);border:1px solid rgba(34,197,94,0.2);border-radius:6px;padding:0.7rem 1rem;margin-bottom:0.75rem;"><span style="color:#22C55E;font-weight:700;">✓</span><span style="font-size:0.85rem;color:#86EFAC;">No adverse media or red flags identified</span></div>', unsafe_allow_html=True)

        # ── Sources ───────────────────────────────────────────────
        if sources:
            with st.expander(f"Sources reviewed ({len(sources)})", expanded=False):
                for s in sources:
                    st.markdown(f'<a href="{s}" target="_blank" style="font-size:0.78rem;color:#388BFD;word-break:break-all;display:block;margin-bottom:0.3rem;">{s}</a>', unsafe_allow_html=True)


def _render_sanctions(sr: dict, directors: list) -> None:
    is_sanctioned = sr.get("is_sanctioned", False)
    hits          = sr.get("hits", [])
    lists         = sr.get("checked_lists", [])
    status_txt    = f"✕  HIT FOUND  ({len(hits)})" if is_sanctioned else "✓  CLEAR"

    with st.expander(f"⚖️  Sanctions Screening   {status_txt}", expanded=True):
        # ── Large status banner ───────────────────────────────────
        color, bg, border, icon_str, msg = (
            ("#EF4444", "rgba(239,68,68,0.09)", "rgba(239,68,68,0.35)", "✕", "SANCTIONED ENTITY DETECTED")
            if is_sanctioned else
            ("#22C55E", "rgba(34,197,94,0.09)", "rgba(34,197,94,0.35)", "✓", "NO SANCTIONS MATCHES FOUND")
        )
        st.markdown(
            f'<div style="text-align:center;background:{bg};border:1.5px solid {border};border-radius:8px;padding:1.25rem 1rem;margin-bottom:1rem;">'
            f'<div style="font-size:2rem;font-weight:800;color:{color};letter-spacing:0.05em;">{icon_str} {msg}</div>'
            f'<div style="font-size:0.78rem;color:{color};opacity:0.7;margin-top:0.35rem;">{len(lists)} list{"s" if len(lists) != 1 else ""} screened · {len(hits)} match{"es" if len(hits) != 1 else ""} found</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Lists checked as individual badges ────────────────────
        _section_label("Lists Screened")
        if lists:
            badges = "".join(
                f'<span style="display:inline-flex;align-items:center;gap:0.3rem;background:rgba(56,139,253,0.1);color:#388BFD;border:1px solid rgba(56,139,253,0.25);border-radius:999px;padding:0.25rem 0.8rem;font-size:0.7rem;font-weight:700;margin:0.2rem;">'
                f'✓ {lst}</span>'
                for lst in lists
            )
            st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:0.3rem;margin-bottom:0.75rem;">{badges}</div>', unsafe_allow_html=True)

        # ── Hits table ────────────────────────────────────────────
        if hits:
            _section_label(f"Matched Entries ({len(hits)})")
            rows = ""
            for h in hits:
                pct = int(h["match_score"] * 100)
                sc  = "#EF4444" if pct >= 85 else "#F59E0B" if pct >= 60 else "#8B949E"
                bar = f'<div style="display:flex;align-items:center;gap:0.5rem;"><div style="flex:1;background:rgba(255,255,255,0.07);border-radius:999px;height:5px;min-width:60px;"><div style="width:{pct}%;height:5px;background:{sc};border-radius:999px;"></div></div><span style="font-size:0.75rem;font-weight:700;color:{sc};min-width:34px;">{pct}%</span></div>'
                raw_details = h.get("details", "")
                if isinstance(raw_details, dict):
                    details_str = ", ".join(f"{k}: {v}" for k, v in raw_details.items())[:60] or "—"
                else:
                    details_str = str(raw_details).strip()[:60] or "—"
                rows += (
                    f'<tr><td style="{_td_style(bold=True)}">{h["matched_name"]}</td>'
                    f'<td style="{_td_style()}"><span style="background:rgba(239,68,68,0.12);color:#EF4444;border-radius:4px;padding:0.15rem 0.5rem;font-size:0.68rem;font-weight:700;">{h["list_name"]}</span></td>'
                    f'<td style="{_td_style()}">{bar}</td>'
                    f'<td style="{_td_style()}">{h.get("entity_type","—")}</td>'
                    f'<td style="{_td_style()}">{h.get("listing_date","—")}</td>'
                    f'<td style="{_td_style()}">{details_str}</td></tr>'
                )
            st.markdown(
                f'<div style="overflow-x:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.07);margin-bottom:0.75rem;"><table style="width:100%;border-collapse:collapse;"><thead><tr><th style="{_th_style()}">Matched Name</th><th style="{_th_style()}">List</th><th style="{_th_style()}">Confidence</th><th style="{_th_style()}">Type</th><th style="{_th_style()}">Listed</th><th style="{_th_style()}">Details</th></tr></thead><tbody>{rows}</tbody></table></div>',
                unsafe_allow_html=True,
            )

        # ── Personnel screened ────────────────────────────────────
        if directors:
            _section_label(f"Associated Personnel Screened ({len(directors)})")
            rows = "".join(
                f'<tr><td style="{_td_style(bold=True)}">{d.get("name","—")}</td><td style="{_td_style()}">{d.get("role","Director")}</td><td style="{_td_style()}"><span style="color:#22C55E;font-weight:600;">✓ Clear</span></td></tr>'
                for d in directors
            )
            st.markdown(
                f'<div style="overflow-x:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.07);"><table style="width:100%;border-collapse:collapse;"><thead><tr><th style="{_th_style()}">Person</th><th style="{_th_style()}">Role</th><th style="{_th_style()}">Sanctions Status</th></tr></thead><tbody>{rows}</tbody></table></div>',
                unsafe_allow_html=True,
            )


def _render_ubo(ubo: dict, entity_name: str) -> None:
    ubos          = ubo.get("ubos", [])
    verified      = ubo.get("ownership_verified", False)
    notes         = ubo.get("notes", "")
    pep_ct        = sum(1 for u in ubos if u.get("pep_status"))
    total_pct     = sum((u.get("ownership_percentage") or 0) for u in ubos)
    multi_layered = any(u.get("intermediate_entities") for u in ubos)

    status_txt = (
        f"⚠  {pep_ct} PEP" if pep_ct
        else (f"✓  {len(ubos)} UBO{'s' if len(ubos) != 1 else ''}" if ubos
              else "—  No Data")
    )

    with st.expander(f"🏢  UBO Structure   {status_txt}", expanded=True):
        # ── Complex structure warning ─────────────────────────────
        if multi_layered:
            st.markdown(
                '<div style="display:flex;gap:0.5rem;background:rgba(167,139,250,0.08);border:1px solid rgba(167,139,250,0.25);border-radius:6px;padding:0.7rem 1rem;margin-bottom:0.75rem;">'
                '<span style="color:#A78BFA;flex-shrink:0;">⚠</span>'
                '<span style="font-size:0.82rem;color:#C9D1D9;">Multi-layered ownership structure detected — indirect chains identified. Enhanced scrutiny recommended.</span>'
                '</div>',
                unsafe_allow_html=True,
            )

        # ── Unverified warning ────────────────────────────────────
        if not verified:
            st.markdown(
                '<div style="display:flex;gap:0.5rem;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:6px;padding:0.7rem 1rem;margin-bottom:0.75rem;">'
                '<span style="color:#F59E0B;flex-shrink:0;">⚠</span>'
                '<span style="font-size:0.82rem;color:#C9D1D9;">Beneficial ownership could not be fully verified. Consider requesting a certified UBO declaration.</span>'
                '</div>',
                unsafe_allow_html=True,
            )

        if not ubos:
            st.markdown(
                '<p style="color:#4A5568;font-size:0.875rem;text-align:center;padding:1.5rem;">No UBO records identified</p>',
                unsafe_allow_html=True,
            )
        else:
            # ── Ownership tree ────────────────────────────────────
            _section_label("Ownership Hierarchy")
            st.markdown(
                f'<div style="background:#1C2230;border-radius:8px;padding:0.9rem 1.1rem;margin-bottom:0.75rem;">'
                f'<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.6rem;">'
                f'<span style="font-size:1rem;">🏢</span>'
                f'<span style="font-size:0.9rem;font-weight:700;color:#E6EDF3;">{entity_name}</span>'
                f'<span style="font-size:0.75rem;color:#4A5568;margin-left:0.25rem;">(Subject Entity · 100%)</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            for idx, u in enumerate(ubos):
                pep      = u.get("pep_status", False)
                pct      = u.get("ownership_percentage")
                pct_w    = min(int(pct), 100) if pct else 0
                pct_s    = f"{pct:.1f}%" if pct is not None else "—%"
                nat      = u.get("nationality", "—")
                color    = "#EF4444" if pep else "#22C55E"
                via_list = u.get("intermediate_entities", [])
                is_last  = idx == len(ubos) - 1
                tree_sym = "└──" if is_last else "├──"

                pep_badge_html = (
                    '<span style="background:rgba(239,68,68,0.12);color:#EF4444;border-radius:999px;padding:0.12rem 0.55rem;font-size:0.66rem;font-weight:700;margin-left:0.4rem;">⚠ PEP</span>'
                    if pep else
                    '<span style="background:rgba(34,197,94,0.1);color:#22C55E;border-radius:999px;padding:0.12rem 0.55rem;font-size:0.66rem;font-weight:700;margin-left:0.4rem;">✓ Clear</span>'
                )
                via_html = (
                    '<div style="font-size:0.7rem;color:#4A5568;margin:0.2rem 0 0 1.5rem;">via ' + " → ".join(via_list) + '</div>'
                    if via_list else ""
                )

                st.markdown(
                    f'<div style="margin-bottom:{("0.6rem" if not is_last else "0.25rem")};">'
                    f'<div style="display:flex;align-items:center;gap:0.5rem;">'
                    f'<span style="font-size:0.82rem;color:#4A5568;font-family:monospace;flex-shrink:0;">{tree_sym}</span>'
                    f'<span style="font-size:0.875rem;font-weight:600;color:#E6EDF3;">{u["name"]}</span>'
                    f'{pep_badge_html}'
                    f'<span style="margin-left:auto;font-size:0.82rem;font-weight:700;color:{color};">{pct_s}</span>'
                    f'</div>'
                    f'{via_html}'
                    f'<div style="display:flex;align-items:center;gap:0.6rem;margin:0.3rem 0 0 1.5rem;">'
                    f'<div style="flex:1;background:rgba(255,255,255,0.06);border-radius:999px;height:4px;">'
                    f'<div style="width:{pct_w}%;height:4px;background:{color};border-radius:999px;"></div></div>'
                    f'<span style="font-size:0.7rem;color:#4A5568;white-space:nowrap;">{nat}</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            st.markdown('</div>', unsafe_allow_html=True)

            # ── Ownership summary bar ─────────────────────────────
            coverage_color = "#22C55E" if total_pct >= 75 else "#F59E0B" if total_pct >= 50 else "#EF4444"
            uncovered = max(0, 100 - total_pct)
            uncov_html = (
                f'<p style="font-size:0.72rem;color:#F59E0B;margin:0.4rem 0 0;">⚠ {uncovered:.0f}% of ownership unaccounted for</p>'
                if uncovered > 25 else ""
            )
            bar_w = f"{min(total_pct, 100):.1f}%"
            st.markdown(
                f'<div style="background:#1C2230;border-radius:6px;padding:0.8rem 1.1rem;margin-bottom:0.75rem;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.45rem;">'
                f'<span style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#4A5568;">Total Identified Ownership</span>'
                f'<span style="font-size:0.875rem;font-weight:700;color:{coverage_color};">{total_pct:.1f}%</span>'
                f'</div>'
                f'<div style="background:rgba(255,255,255,0.06);border-radius:999px;height:8px;overflow:hidden;">'
                f'<div style="width:{bar_w};height:8px;background:linear-gradient(90deg,{coverage_color}88,{coverage_color});border-radius:999px;"></div>'
                f'</div>'
                f'{uncov_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

        if notes:
            st.markdown(
                f'<p style="font-size:0.8rem;color:#8B949E;background:#1C2230;border-radius:6px;padding:0.75rem;margin-top:0.25rem;line-height:1.6;">{notes}</p>',
                unsafe_allow_html=True,
            )


def _recommended_actions(level: str, flags: list) -> list[str]:
    has_sanctions = any("SANCTIONS" in f.upper() for f in flags)
    has_pep       = any("PEP" in f.upper() for f in flags)

    if has_sanctions:
        return [
            "Do NOT onboard — notify Compliance Officer immediately",
            "File a Suspicious Activity Report (SAR) if legally required",
            "Freeze all pending transactions with this entity",
            "Retain all screening records for regulatory inspection",
        ]

    action_map: dict[str, list[str]] = {
        "Red": [
            "Escalate to Senior Compliance Officer before proceeding",
            "Conduct Enhanced Due Diligence (EDD) investigation",
            "Obtain written senior management approval for onboarding",
            "Implement enhanced ongoing transaction monitoring",
            "Document full risk rationale in compliance file",
        ],
        "Amber": [
            "Conduct standard Customer Due Diligence (CDD) review",
            "Request supporting documentation to verify entity",
            "Apply enhanced monitoring with quarterly review cycle",
            "Document risk assessment rationale in compliance file",
        ],
        "Green": [
            "Proceed with standard onboarding procedures",
            "Apply annual KYC refresh cycle",
            "Retain screening records per data retention policy",
        ],
    }

    actions = list(action_map.get(level, action_map["Green"]))
    if has_pep:
        actions.insert(0, "Obtain MLRO sign-off — Enhanced PEP monitoring required")
    return actions[:5]


def _render_risk_factors(risk: dict, flags: list, elapsed: float) -> None:
    factors  = risk.get("factors", [])
    summary  = risk.get("summary", "—")
    level    = risk.get("level", "Green")
    score    = risk.get("score", 0)
    cfg      = RISK_CFG[level]
    color    = cfg["hex"]
    glow     = cfg["glow"]
    status_txt = f"{cfg['icon']}  {cfg['label']}  ·  {score}/100"
    actions    = _recommended_actions(level, flags)
    escalate   = level == "Red" or any("SANCTIONS" in f.upper() or "PEP" in f.upper() for f in flags)

    with st.expander(f"📊  Risk Assessment   {status_txt}", expanded=True):
        # ── Score + escalation side by side ──────────────────────
        r, cx, cy = 52, 80, 80
        circ      = 2 * math.pi * r
        progress  = (score / 100) * circ
        remaining = circ - progress
        offset    = circ / 4
        gauge_svg = (
            f'<svg viewBox="0 0 160 160" width="120" height="120">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="10"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="10" stroke-linecap="round"'
            f' stroke-dasharray="{progress:.2f} {remaining:.2f}" stroke-dashoffset="{offset:.2f}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="38" fill="{glow}"/>'
            f'<text x="{cx}" y="{cy-6}" text-anchor="middle" font-family="Inter,sans-serif" font-size="30" font-weight="800" fill="{color}">{score}</text>'
            f'<text x="{cx}" y="{cy+12}" text-anchor="middle" font-family="Inter,sans-serif" font-size="8" font-weight="600" fill="{color}" opacity="0.6" letter-spacing="1">/ 100</text>'
            f'</svg>'
        )
        esc_color   = "#EF4444" if escalate else "#22C55E"
        esc_bg      = "rgba(239,68,68,0.1)" if escalate else "rgba(34,197,94,0.08)"
        esc_border  = "rgba(239,68,68,0.3)" if escalate else "rgba(34,197,94,0.25)"
        esc_icon    = "⚠ YES" if escalate else "✓ NO"
        elapsed_str = f"{elapsed:.0f}s" if elapsed else "—"
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:1.5rem;background:#1C2230;border-radius:8px;padding:1rem 1.25rem;margin-bottom:1rem;">'
            f'<div style="flex-shrink:0;">{gauge_svg}</div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:1rem;font-weight:800;color:{color};letter-spacing:-0.01em;margin-bottom:0.3rem;">{cfg["label"]}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.6rem;">'
            f'<div style="background:{esc_bg};border:1px solid {esc_border};border-radius:6px;padding:0.3rem 0.75rem;font-size:0.7rem;font-weight:700;color:{esc_color};">ESCALATION REQUIRED: {esc_icon}</div>'
            f'<div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:0.3rem 0.75rem;font-size:0.7rem;font-weight:600;color:#8B949E;">⏱ {elapsed_str} total</div>'
            f'</div>'
            f'<p style="font-size:0.8rem;color:#C9D1D9;line-height:1.65;margin:0;">{summary}</p>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        # ── Factor progress bars ──────────────────────────────────
        if factors:
            _section_label("Risk Factor Breakdown")
            for f in sorted(factors, key=lambda x: x.get("weight", 0), reverse=True):
                cat   = f["category"]
                fc    = FACTOR_COLORS.get(cat, "#8B949E")
                pct   = int(f.get("weight", 0) * 100)
                score_label = f"{pct:02d}/100"
                bar_fill = "█" * (pct // 10) + "░" * (10 - pct // 10)
                st.markdown(
                    f'<div style="margin-bottom:0.85rem;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem;">'
                    f'<div style="display:flex;align-items:center;gap:0.5rem;">'
                    f'<span style="background:{fc}22;color:{fc};border-radius:4px;padding:0.1rem 0.42rem;font-size:0.65rem;font-weight:700;letter-spacing:0.05em;">{cat}</span>'
                    f'<span style="font-size:0.78rem;color:#8B949E;">{f.get("description","")}</span>'
                    f'</div>'
                    f'<span style="font-size:0.72rem;font-weight:700;color:{fc};font-family:monospace;">{score_label}</span>'
                    f'</div>'
                    f'<div style="background:rgba(255,255,255,0.06);border-radius:999px;height:6px;">'
                    f'<div style="width:{pct}%;height:6px;background:linear-gradient(90deg,{fc}66,{fc});border-radius:999px;transition:width 0.6s;"></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

        # ── Recommended actions ───────────────────────────────────
        if actions:
            _section_label("Recommended Actions")
            items_html = "".join(
                f'<div style="display:flex;align-items:flex-start;gap:0.6rem;padding:0.5rem 0;border-bottom:1px solid rgba(255,255,255,0.05);">'
                f'<span style="background:rgba(56,139,253,0.15);color:#388BFD;border-radius:999px;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:0.65rem;font-weight:800;flex-shrink:0;">{i+1}</span>'
                f'<span style="font-size:0.82rem;color:#C9D1D9;line-height:1.55;">{action}</span>'
                f'</div>'
                for i, action in enumerate(actions)
            )
            st.markdown(
                f'<div style="background:#1C2230;border-radius:6px;padding:0.6rem 0.9rem;margin-top:0.25rem;">{items_html}</div>',
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


def _build_pdf(report: dict) -> bytes:
    """Generate a professional A4 PDF. Requires fpdf2 (pip install fpdf2)."""
    try:
        from fpdf import FPDF  # type: ignore
    except ImportError:
        raise RuntimeError("fpdf2 not installed — run: pip install fpdf2")

    e     = report.get("entity", {})
    rr    = report.get("risk_rating", {})
    rf    = report.get("research_findings", {})
    sr    = report.get("sanctions_results", {})
    ubo_d = report.get("ubo_structure", {})
    flags = report.get("flags", [])
    ts    = report.get("timestamp", "")[:10]

    level    = rr.get("level", "Green")
    score    = rr.get("score", 0)
    risk_rgb: tuple[int, int, int] = {
        "Green": (34, 197, 94), "Amber": (245, 158, 11), "Red": (239, 68, 68),
    }.get(level, (34, 197, 94))

    # ── Layout & palette ──────────────────────────────────────────────────────
    PW, LM, RM = 210, 18, 18
    TW = PW - LM - RM
    C_DARK:   tuple[int, int, int] = (15,  23,  42)
    C_MUTED:  tuple[int, int, int] = (100, 116, 139)
    C_BG:     tuple[int, int, int] = (248, 250, 252)
    C_WHITE:  tuple[int, int, int] = (255, 255, 255)
    C_BORDER: tuple[int, int, int] = (226, 232, 240)

    # Sanitise text for Helvetica (Latin-1 only — no Unicode arrows/dashes)
    def c(s: object, maxlen: int = 200) -> str:
        t = str(s) if s is not None else "-"
        if not t or t in ("None", "null"):
            t = "-"
        t = (t.replace("—", "-").replace("–", "-")
              .replace("’", "'").replace("‘", "'")
              .replace("“", '"').replace("”", '"')
              .replace("•", "*").replace("…", "...")
              .replace(" ", " ").replace("→", "->")
              .replace("•", "*").replace("·", ".")
              .replace("✓", "OK").replace("✕", "X")
              .replace("⚠", "!").replace("×", "x"))
        t = t.encode("latin-1", errors="replace").decode("latin-1")
        return t[:maxlen]

    class _KycPDF(FPDF):
        def footer(self) -> None:
            self.set_y(-18)
            self.set_draw_color(*C_BORDER)
            self.line(LM, self.get_y(), LM + TW, self.get_y())
            self.ln(2)
            self.set_x(LM)
            self.set_font("Helvetica", "", 6.5)
            self.set_text_color(*C_MUTED)
            self.cell(
                TW * 0.76, 4,
                "For compliance screening purposes only. Not legal advice. "
                "Verify all findings independently. Powered by KYC Intelligence Platform.",
            )
            self.cell(TW * 0.24, 4, c(f"Page {self.page_no()}  |  {ts}"), align="R")

    pdf = _KycPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(LM, 15, RM)
    pdf.add_page()

    # ── Cover header bar ──────────────────────────────────────────────────────
    pdf.set_fill_color(*C_DARK)
    pdf.rect(0, 0, PW, 26, style="F")
    pdf.set_fill_color(*risk_rgb)
    pdf.rect(0, 0, 5, 26, style="F")
    pdf.set_xy(LM, 6)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*C_WHITE)
    pdf.cell(TW * 0.6, 7, "KYC SCREENING REPORT")
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(175, 188, 205)
    pdf.cell(TW * 0.4, 7, f"Date: {ts}   |   KYC Intelligence Platform", align="R")
    pdf.set_xy(LM, 15)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(155, 170, 190)
    entity_line = c(f"{e.get('name','-')}  |  {e.get('jurisdiction','-')}  |  {e.get('industry','') or ''}", 90)
    pdf.cell(TW, 6, entity_line)

    # ── Risk summary box ──────────────────────────────────────────────────────
    pdf.set_xy(LM, 31)
    pdf.set_fill_color(*risk_rgb)
    pdf.rect(LM, 31, 5, 32, style="F")
    pdf.set_fill_color(*C_BG)
    pdf.rect(LM + 5, 31, TW - 5, 32, style="F")
    pdf.set_xy(LM + 9, 35)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(*risk_rgb)
    pdf.cell(32, 12, str(score))
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(16, 12, "/ 100")
    label_map = {"Green": "LOW RISK", "Amber": "MEDIUM RISK", "Red": "HIGH RISK"}
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*risk_rgb)
    pdf.cell(52, 12, label_map.get(level, level.upper()))
    escalate = level == "Red" or any("SANCTIONS" in f.upper() or "PEP" in f.upper() for f in flags)
    esc_rgb  = (210, 50, 50) if escalate else (34, 160, 80)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*esc_rgb)
    pdf.cell(TW - 97, 12, "ESCALATION: YES" if escalate else "ESCALATION: NOT REQUIRED", align="R")
    pdf.set_xy(LM + 9, 49)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*C_DARK)
    pdf.multi_cell(TW - 12, 4.5, c(rr.get("summary", "-"), 220))
    pdf.ln(4)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def sec(title: str) -> None:
        pdf.set_x(LM)
        pdf.set_fill_color(*C_DARK)
        pdf.set_text_color(*C_WHITE)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(TW, 6.5, f"  {title}", ln=1, fill=True)
        pdf.ln(2)
        pdf.set_text_color(*C_DARK)

    def kv(label: str, value: object, shade: bool = False) -> None:
        pdf.set_fill_color(*(C_BG if shade else C_WHITE))
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(*C_MUTED)
        pdf.cell(42, 5.5, label, fill=True)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*C_DARK)
        pdf.cell(TW - 42, 5.5, c(value, 90), fill=True, ln=1)

    def tbl_hdr(cols: list[tuple[str, float]]) -> None:
        pdf.set_fill_color(*C_DARK)
        pdf.set_text_color(*C_WHITE)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_x(LM)
        for col, w in cols:
            pdf.cell(w, 5.5, col, fill=True)
        pdf.ln()

    def tbl_row(cols: list[tuple[object, float]], shade: bool = False) -> None:
        pdf.set_fill_color(*(C_BG if shade else C_WHITE))
        pdf.set_text_color(*C_DARK)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_x(LM)
        for val, w in cols:
            pdf.cell(w, 5.5, c(val, 42), fill=True)
        pdf.ln()

    # ── Entity details ────────────────────────────────────────────────────────
    sec("ENTITY DETAILS")
    kv("Company Name",    e.get("name"))
    kv("Jurisdiction",    e.get("jurisdiction"),          shade=True)
    kv("Registration No", e.get("registration_number"))
    kv("Industry",        e.get("industry"),              shade=True)
    kv("Address",         e.get("address"))
    kv("Website",         e.get("website"),               shade=True)
    kv("Incorporated",    rf.get("incorporation_date"))
    pdf.ln(4)

    # ── Research findings ─────────────────────────────────────────────────────
    sec("RESEARCH FINDINGS")
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*C_DARK)
    pdf.multi_cell(TW, 5, c(rf.get("summary")))
    pdf.ln(2)

    dirs = rf.get("directors", [])
    if dirs:
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(*C_MUTED)
        pdf.cell(TW, 5, "Key Personnel:", ln=1)
        tbl_hdr([("Name", 55), ("Role", 42), ("Nationality", 22), ("Date of Birth", TW - 119)])
        for i, d in enumerate(dirs):
            tbl_row([
                (d.get("name"), 55), (d.get("role"), 42),
                (d.get("nationality"), 22), (d.get("date_of_birth"), TW - 119),
            ], shade=i % 2 == 0)
        pdf.ln(2)

    adverse = rf.get("adverse_media", [])
    if adverse:
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(200, 50, 50)
        pdf.cell(TW, 5, f"Adverse Media ({len(adverse)} items):", ln=1)
        pdf.set_text_color(*C_DARK)
        for item in adverse:
            pdf.set_x(LM + 4)
            pdf.set_font("Helvetica", "", 8)
            pdf.multi_cell(TW - 4, 4.8, c(f"[!]  {item}"))
    else:
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(34, 150, 80)
        pdf.cell(TW, 5, "[OK]  No adverse media identified", ln=1)
        pdf.set_text_color(*C_DARK)
    pdf.ln(4)

    # ── Sanctions ─────────────────────────────────────────────────────────────
    sec("SANCTIONS SCREENING")
    is_sanc = sr.get("is_sanctioned", False)
    hits    = sr.get("hits", [])
    lists   = sr.get("checked_lists", [])
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "B", 10)
    if is_sanc:
        pdf.set_text_color(200, 40, 40)
        pdf.cell(TW, 7, f"[X]  SANCTIONED -- {len(hits)} match(es) found", ln=1)
    else:
        pdf.set_text_color(34, 150, 80)
        pdf.cell(TW, 7, "[OK]  CLEAR -- No sanctions matches found", ln=1)
    pdf.set_text_color(*C_MUTED)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_x(LM)
    pdf.multi_cell(TW, 4.5, c(f"Lists screened ({len(lists)}): {', '.join(lists)}"))
    pdf.ln(1.5)
    if hits:
        tbl_hdr([("Matched Name", 52), ("List", 42), ("Score", 18), ("Type", 26), ("Listed", TW - 138)])
        for i, h in enumerate(hits):
            tbl_row([
                (h.get("matched_name"), 52), (h.get("list_name"), 42),
                (f"{int(h.get('match_score', 0) * 100)}%", 18),
                (h.get("entity_type"), 26), (h.get("listing_date"), TW - 138),
            ], shade=i % 2 == 0)
    pdf.set_text_color(*C_DARK)
    pdf.ln(4)

    # ── UBO structure ─────────────────────────────────────────────────────────
    sec("BENEFICIAL OWNERSHIP (UBO)")
    ubos     = ubo_d.get("ubos", [])
    verified = ubo_d.get("ownership_verified", False)
    notes_u  = ubo_d.get("notes", "")
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(TW, 5, "[OK] Verified" if verified else "[!] Ownership could not be fully verified", ln=1)
    pdf.ln(1)
    if ubos:
        tbl_hdr([("Beneficial Owner", 58), ("Stake %", 20), ("Nationality", 22), ("PEP", 14), ("Intermediate Chain", TW - 114)])
        for i, u in enumerate(ubos):
            via = " -> ".join(u.get("intermediate_entities", []))[:42] or "Direct"
            pct = f"{u.get('ownership_percentage', 0):.1f}%" if u.get("ownership_percentage") is not None else "-"
            tbl_row([
                (u.get("name"), 58), (pct, 20), (u.get("nationality"), 22),
                ("YES" if u.get("pep_status") else "No", 14), (via, TW - 114),
            ], shade=i % 2 == 0)
    if notes_u:
        pdf.ln(2)
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "I", 7.5)
        pdf.set_text_color(*C_MUTED)
        pdf.multi_cell(TW, 4.5, c(f"Note: {notes_u}"))
        pdf.set_text_color(*C_DARK)
    pdf.ln(4)

    # ── Risk factor breakdown ─────────────────────────────────────────────────
    sec("RISK FACTOR BREAKDOWN")
    factors = rr.get("factors", [])
    if factors:
        tbl_hdr([("Factor", 38), ("Description", TW - 58), ("Score", 20)])
        for i, fac in enumerate(sorted(factors, key=lambda x: x.get("weight", 0), reverse=True)):
            pct = int(fac.get("weight", 0) * 100)
            tbl_row([
                (fac.get("category"), 38),
                (fac.get("description"), TW - 58),
                (f"{pct:02d}/100", 20),
            ], shade=i % 2 == 0)
    pdf.ln(4)

    # ── Recommended actions ───────────────────────────────────────────────────
    actions = _recommended_actions(level, flags)
    if actions:
        sec("RECOMMENDED ACTIONS")
        for i, action in enumerate(actions, 1):
            pdf.set_x(LM + 3)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(*C_DARK)
            pdf.multi_cell(TW - 3, 5, c(f"{i}.  {action}"))
        pdf.ln(2)

    # ── Compliance flags ──────────────────────────────────────────────────────
    if flags:
        sec("COMPLIANCE FLAGS  --  REQUIRES SENIOR REVIEW")
        for flag in flags:
            pdf.set_x(LM + 3)
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(200, 40, 40)
            pdf.multi_cell(TW - 3, 5.5, c(f"[!]  {flag}"))
        pdf.ln(2)
        pdf.set_text_color(*C_DARK)

    return bytes(pdf.output())


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
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "📑  Download PDF",
            data=_build_pdf(report),
            file_name=f"KYC_{name_slug}_{ts_slug}.pdf",
            mime="application/pdf",
        )
    with c2:
        st.download_button(
            "📄  Download Markdown",
            data=_build_markdown(report),
            file_name=f"KYC_{name_slug}_{ts_slug}.md",
            mime="text/markdown",
        )
    with c3:
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
    directors = research.get("directors", [])
    _render_research(research, entity)
    _render_sanctions(sanctions, directors)
    _render_ubo(ubo, entity.get("name", "—"))
    _render_risk_factors(risk, flags, elapsed)

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
# Demo mode helpers
# ─────────────────────────────────────────────────────────────────────────────

def _render_demo_banner() -> None:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:0.6rem;'
        'background:rgba(56,139,253,0.07);border:1px solid rgba(56,139,253,0.22);'
        'border-radius:8px;padding:0.6rem 1rem;margin-bottom:1rem;">'
        '<span style="font-size:0.95rem;flex-shrink:0;">🎯</span>'
        '<div>'
        '<span style="font-size:0.78rem;font-weight:700;color:#388BFD;">Demo Mode</span>'
        '<span style="font-size:0.78rem;color:#8B949E;"> — using sample data for demonstration purposes. '
        'No external API calls are made.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_demo_controls() -> tuple[bool, str]:
    """Inline demo controls row rendered in the main page. Returns (demo_mode, scenario_key)."""
    c_tog, c_sel, c_badge, c_spacer = st.columns([1.6, 3.2, 2.2, 4.0])
    with c_tog:
        demo_mode: bool = st.toggle(
            "🎯 Demo Mode",
            key="demo_mode_toggle",
            help="Use hardcoded sample scenarios — no API calls",
        )
    scenario_key = "clean_corp"
    if demo_mode:
        labels = [lbl for _, lbl, _ in DEMO_SCENARIOS]
        with c_sel:
            selected_label: str = st.selectbox(
                "demo_scenario",
                options=labels,
                key="demo_scenario_select",
                label_visibility="collapsed",
            )
        scenario_key = next(k for k, lbl, _ in DEMO_SCENARIOS if lbl == selected_label)
        cfg   = RISK_CFG[MOCK_REPORTS[scenario_key]["risk_rating"]["level"]]
        score = MOCK_REPORTS[scenario_key]["risk_rating"]["score"]
        with c_badge:
            st.markdown(
                f'<div style="margin-top:0.35rem;display:inline-flex;align-items:center;'
                f'background:{cfg["glow"]};border:1px solid {cfg["hex"]}55;border-radius:999px;'
                f'padding:0.3rem 0.85rem;white-space:nowrap;">'
                f'<span style="font-size:0.72rem;font-weight:700;color:{cfg["hex"]};">'
                f'{cfg["icon"]} {cfg["label"]} · {score}/100</span></div>',
                unsafe_allow_html=True,
            )
    return demo_mode, scenario_key


# ─────────────────────────────────────────────────────────────────────────────
# Animated stepper while API call runs (threading)
# ─────────────────────────────────────────────────────────────────────────────

def _run_demo_screening(mock_report: dict) -> None:
    """Animate the stepper quickly, then surface the mock report — no API call."""
    stepper_ph = st.empty()
    t_start    = time.time()
    # Cycle through all 4 agent steps, ~0.7 s each
    for active in range(len(AGENTS)):
        for _ in range(4):
            stepper_ph.markdown(_stepper_html(active, time.time() - t_start), unsafe_allow_html=True)
            time.sleep(0.175)
    stepper_ph.empty()

    elapsed = time.time() - t_start
    st.session_state["last_report"]       = mock_report
    st.session_state["screening_elapsed"] = elapsed
    history = st.session_state.get("history", [])
    history.append(mock_report)
    st.session_state["history"] = history[-8:]
    st.rerun()


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

# ── Input row ─────────────────────────────────────────────────────────────────
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

# ── Demo controls (toggle + scenario selector, rendered inline) ───────────────
demo_mode, scenario_key = _render_demo_controls()

# ── Demo banner ───────────────────────────────────────────────────────────────
if demo_mode:
    _render_demo_banner()
else:
    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)

# ── Dispatch ──────────────────────────────────────────────────────────────────
if submitted:
    if demo_mode:
        mock = copy.deepcopy(MOCK_REPORTS[scenario_key])
        if company_name.strip():
            mock["entity"]["name"] = company_name.strip()
        _run_demo_screening(mock)
    elif not company_name:
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
        <strong style="color:#8B949E;">Gemini 2.5 Flash</strong> ·
        <strong style="color:#8B949E;">LangGraph</strong> ·
        <strong style="color:#8B949E;">OpenSanctions</strong>
    </span>
</div>
    """,
    unsafe_allow_html=True,
)
