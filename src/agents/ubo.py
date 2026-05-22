from __future__ import annotations

import functools

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.orchestrator.state import GraphState
from src.models import UBOStructure
from src.tools.search import web_search
from src.tools.company_registry import lookup_company_registry
from src.agents._llm import get_llm, ainvoke_with_retry

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a UBO (Ultimate Beneficial Ownership) investigator conducting KYC due diligence.

From the company registry data and web search results provided, map the full ownership structure:
- Identify all individuals owning ≥ 25% (or the applicable local threshold)
- Note indirect ownership chains through intermediate entities
- Flag any Politically Exposed Persons (PEPs)
- Note any nominee or trust arrangements that obscure ownership

If beneficial ownership cannot be determined, set ownership_verified=false and explain in notes."""

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", (
        "Company: {name}\nJurisdiction: {jurisdiction}\n"
        "Registration number: {reg_number}\n\n"
        "Registry data:\n{registry_data}\n\n"
        "Additional web search results:\n{search_results}"
    )),
])


@functools.lru_cache(maxsize=1)
def _chain():
    return _prompt | get_llm().with_structured_output(UBOStructure)


async def run(state: GraphState) -> dict:
    entity = state["entity"]
    log = logger.bind(agent="ubo", entity=entity.name)
    log.info("starting")

    registry_data, search_results = await _fetch_sources(entity)

    structure: UBOStructure = await ainvoke_with_retry(_chain(), {
        "name": entity.name,
        "jurisdiction": entity.jurisdiction,
        "reg_number": entity.registration_number or "unknown",
        "registry_data": str(registry_data),
        "search_results": search_results,
    })

    pep_ubos = [u.name for u in structure.ubos if u.pep_status]
    new_flags: list[str] = [f"PEP IDENTIFIED: {', '.join(pep_ubos)}"] if pep_ubos else []

    log.info("complete", ubos=len(structure.ubos), peps=len(pep_ubos))
    return {"ubo_structure": structure, "flags": new_flags}


async def _fetch_sources(entity) -> tuple[dict, str]:
    registry_data = await lookup_company_registry(
        entity.name, entity.jurisdiction, entity.registration_number
    )
    raw = await web_search(f"{entity.name} shareholders beneficial owner UBO {entity.jurisdiction}")
    search_results = "\n\n".join(f"[{r['url']}]\n{r['content']}" for r in raw)
    return registry_data, search_results
