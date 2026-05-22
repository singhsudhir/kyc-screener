from __future__ import annotations

import functools

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.orchestrator.state import GraphState
from src.models import SanctionsResults
from src.tools.sanctions_api import query_opensanctions
from src.agents._llm import build_chain

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a sanctions screening specialist. Review the raw API results from
OpenSanctions and produce a structured sanctions assessment for the queried entity.

Classify each hit with an accurate match_score (0.0–1.0) reflecting name similarity and
contextual overlap. Set is_sanctioned=true only if at least one hit has match_score ≥ 0.85."""

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "Entity name: {name}\nJurisdiction: {jurisdiction}\n\nAPI results:\n{api_results}"),
])


@functools.lru_cache(maxsize=1)
def _chain():
    return build_chain(_prompt, SanctionsResults)


async def run(state: GraphState) -> dict:
    entity = state["entity"]
    log = logger.bind(agent="sanctions", entity=entity.name)
    log.info("starting")

    api_results = await query_opensanctions(entity.name, entity.jurisdiction)

    results: SanctionsResults = await _chain().ainvoke({
        "name": entity.name,
        "jurisdiction": entity.jurisdiction,
        "api_results": str(api_results),
    })

    new_flags: list[str] = []
    if results.is_sanctioned:
        new_flags.append(
            f"SANCTIONS HIT: {entity.name} matched on {', '.join(results.checked_lists)}"
        )

    log.info("complete", hits=len(results.hits), is_sanctioned=results.is_sanctioned)
    return {"sanctions_results": results, "flags": new_flags}
