from __future__ import annotations

import functools

import structlog
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from src.orchestrator.state import GraphState
from src.models import ResearchFindings
from src.tools.search import web_search

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a KYC research analyst. Given a company name and jurisdiction,
analyse the web search results and extract:
- A factual summary of the company's business and history
- Known directors / key personnel
- Any adverse media, legal proceedings, or regulatory actions
- Incorporation date if available

Be objective and cite sources. If information is unavailable, say so explicitly."""

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "Company: {name}\nJurisdiction: {jurisdiction}\n\nSearch results:\n{search_results}"),
])


@functools.lru_cache(maxsize=1)
def _chain():
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)
    return _prompt | llm.with_structured_output(ResearchFindings)


async def run(state: GraphState) -> dict:
    entity = state["entity"]
    log = logger.bind(agent="research", entity=entity.name)
    log.info("starting")

    query = f"{entity.name} {entity.jurisdiction} company information directors adverse media"
    raw_results = await web_search(query)

    formatted = "\n\n".join(f"[{r['url']}]\n{r['content']}" for r in raw_results)

    findings: ResearchFindings = await _chain().ainvoke({
        "name": entity.name,
        "jurisdiction": entity.jurisdiction,
        "search_results": formatted,
    })

    findings = findings.model_copy(update={"raw_results": raw_results})
    log.info("complete", sources=len(findings.sources), adverse_media=len(findings.adverse_media))
    return {"research_findings": findings}
