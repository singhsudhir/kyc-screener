from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict

from src.models import (
    CompanyEntity,
    KYCReport,
    ResearchFindings,
    SanctionsResults,
    UBOStructure,
    RiskRating,
)


class GraphState(TypedDict, total=False):
    """Shared state that flows through the LangGraph workflow."""

    # Input
    entity: CompanyEntity

    # Agent outputs (populated as the graph executes)
    research_findings: Optional[ResearchFindings]
    sanctions_results: Optional[SanctionsResults]
    ubo_structure: Optional[UBOStructure]
    risk_rating: Optional[RiskRating]

    # Orchestrator metadata
    flags: list[str]
    errors: list[str]

    # Final output
    report: Optional[KYCReport]
