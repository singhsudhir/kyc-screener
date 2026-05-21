from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.entities import CompanyEntity, PersonEntity
from src.models.risk import RiskRating


class ResearchFindings(BaseModel):
    """Output produced by the Research Agent."""

    model_config = ConfigDict(frozen=True)

    summary: str = Field(..., description="Narrative summary of publicly available information")
    sources: list[str] = Field(default_factory=list, description="URLs / references consulted")
    incorporation_date: Optional[str] = None
    directors: list[PersonEntity] = Field(default_factory=list)
    adverse_media: list[str] = Field(default_factory=list, description="Adverse media headlines or excerpts")
    raw_results: list[dict] = Field(default_factory=list, description="Raw search result payloads")


class SanctionsHit(BaseModel):
    """A single match returned from a sanctions list lookup."""

    model_config = ConfigDict(frozen=True)

    list_name: str = Field(..., description="Name of the sanctions list, e.g. 'OFAC SDN', 'EU Consolidated'")
    matched_name: str = Field(..., description="Name as it appears on the sanctions list")
    match_score: float = Field(..., ge=0.0, le=1.0, description="Fuzzy match confidence (0–1)")
    entity_type: Optional[str] = Field(None, description="'individual' | 'entity' | 'vessel' etc.")
    listing_date: Optional[str] = None
    details: dict = Field(default_factory=dict, description="Additional structured data from the list entry")

    @field_validator("match_score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 4)


class SanctionsResults(BaseModel):
    """Aggregated sanctions screening output."""

    model_config = ConfigDict(frozen=True)

    screened_name: str
    hits: list[SanctionsHit] = Field(default_factory=list)
    is_sanctioned: bool = Field(..., description="True if any hit has match_score ≥ 0.85")
    checked_lists: list[str] = Field(default_factory=list)


class UBORecord(BaseModel):
    """A single Ultimate Beneficial Owner entry."""

    model_config = ConfigDict(frozen=True)

    name: str
    ownership_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)
    nationality: Optional[str] = Field(None, description="ISO-3166 alpha-2")
    pep_status: bool = Field(False, description="True if the UBO is a Politically Exposed Person")
    pep_details: Optional[str] = None
    indirect_ownership: bool = Field(False, description="True if ownership is via intermediate entities")
    intermediate_entities: list[str] = Field(default_factory=list)


class UBOStructure(BaseModel):
    """Complete UBO map for the screened entity."""

    model_config = ConfigDict(frozen=True)

    subject_name: str
    ubos: list[UBORecord] = Field(default_factory=list)
    ownership_verified: bool = False
    notes: str = ""


class KYCReport(BaseModel):
    """Final compiled KYC report produced by the Orchestrator."""

    entity: CompanyEntity
    research_findings: ResearchFindings
    sanctions_results: SanctionsResults
    ubo_structure: UBOStructure
    risk_rating: RiskRating
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    flags: list[str] = Field(default_factory=list, description="High-priority issues requiring human review")
    report_version: str = "1.0"

    def is_high_risk(self) -> bool:
        return self.risk_rating.level == "Red"

    def requires_review(self) -> bool:
        return self.risk_rating.level in ("Amber", "Red") or bool(self.flags)
