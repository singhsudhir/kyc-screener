from __future__ import annotations

import operator
from typing import Annotated, Optional
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

    # Reducer-annotated lists so parallel agents can safely append without conflict
    flags: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]

    # Final output
    report: Optional[KYCReport]
