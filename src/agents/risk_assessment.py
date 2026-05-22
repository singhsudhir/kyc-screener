from __future__ import annotations

import functools

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.orchestrator.state import GraphState
from src.models import RiskRating
from src.agents._llm import build_chain

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a senior KYC risk analyst. Based on the research, sanctions screening,
and UBO findings provided, assign an overall risk rating.

Rating scale:
- Green  (score 0–33):  Low risk — no significant concerns identified
- Amber  (score 34–66): Medium risk — some concerns; enhanced due diligence recommended
- Red    (score 67–100): High risk — serious concerns; senior review required before onboarding

Weight the following risk factors:
1. Sanctions exposure (highest weight)
2. PEP connections
3. Adverse media / legal proceedings
4. Opaque ownership structure
5. High-risk jurisdiction
6. Industry risk (e.g. gambling, crypto, arms)

Provide a concise but complete summary explaining the rating."""

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", (
        "Entity: {name} ({jurisdiction})\n\n"
        "=== RESEARCH FINDINGS ===\n{research_summary}\n"
        "Adverse media: {adverse_media}\n\n"
        "=== SANCTIONS RESULTS ===\n"
        "Is sanctioned: {is_sanctioned}\n"
        "Hits: {sanctions_hits}\n\n"
        "=== UBO STRUCTURE ===\n{ubo_summary}\n"
        "PEPs: {pep_list}\n"
        "Ownership verified: {ownership_verified}\n\n"
        "=== FLAGS ===\n{flags}"
    )),
])


@functools.lru_cache(maxsize=1)
def _chain():
    return build_chain(_prompt, RiskRating)


async def run(state: GraphState) -> dict:
    entity   = state["entity"]
    research = state["research_findings"]
    sanctions = state["sanctions_results"]
    ubo      = state["ubo_structure"]
    flags    = state.get("flags", [])

    log = logger.bind(agent="risk_assessment", entity=entity.name)
    log.info("starting")

    pep_list = [u.name for u in ubo.ubos if u.pep_status] if ubo else []
    sanctions_hits = (
        [f"{h.list_name}: {h.matched_name} ({h.match_score:.0%})" for h in sanctions.hits]
        if sanctions else []
    )

    rating: RiskRating = await _chain().ainvoke({
        "name":               entity.name,
        "jurisdiction":       entity.jurisdiction,
        "research_summary":   research.summary if research else "N/A",
        "adverse_media":      "; ".join(research.adverse_media) if research else "none",
        "is_sanctioned":      str(sanctions.is_sanctioned) if sanctions else "unknown",
        "sanctions_hits":     "; ".join(sanctions_hits) or "none",
        "ubo_summary":        _format_ubo(ubo),
        "pep_list":           "; ".join(pep_list) or "none",
        "ownership_verified": str(ubo.ownership_verified) if ubo else "unknown",
        "flags":              "\n".join(flags) or "none",
    })

    log.info("complete", level=rating.level, score=rating.score)
    return {"risk_rating": rating}


def _format_ubo(ubo) -> str:
    if not ubo or not ubo.ubos:
        return "No UBO data available"
    lines = []
    for u in ubo.ubos:
        pct = f"{u.ownership_percentage:.1f}%" if u.ownership_percentage else "unknown %"
        lines.append(f"- {u.name} ({pct}, nationality: {u.nationality or 'unknown'})")
    return "\n".join(lines)
