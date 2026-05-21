from __future__ import annotations

# Load .env before any src.* imports — agents instantiate the LLM at module level
from dotenv import load_dotenv
load_dotenv()

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.models import CompanyEntity, KYCReport
from src.orchestrator.graph import kyc_graph

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="KYC Screener API",
    description="Multi-Agent KYC Screening System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScreeningRequest(BaseModel):
    name: str
    jurisdiction: str
    registration_number: str | None = None
    address: str | None = None
    website: str | None = None
    industry: str | None = None


@app.post("/screen", response_model=KYCReport)
async def screen_entity(request: ScreeningRequest) -> KYCReport:
    """Run a full KYC screening on a company entity."""
    entity = CompanyEntity(**request.model_dump())
    log = logger.bind(entity=entity.name, jurisdiction=entity.jurisdiction)
    log.info("screening_started")

    try:
        result = await kyc_graph.ainvoke({"entity": entity, "flags": [], "errors": []})
    except Exception as exc:
        log.error("screening_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Screening failed: {exc}") from exc

    report: KYCReport = result["report"]
    log.info("screening_complete", risk_level=report.risk_rating.level, score=report.risk_rating.score)
    return report


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
