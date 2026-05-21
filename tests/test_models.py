from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    CompanyEntity,
    RiskRating,
    RiskFactor,
    SanctionsHit,
    SanctionsResults,
    UBORecord,
    UBOStructure,
    ResearchFindings,
    KYCReport,
)


def _make_entity() -> CompanyEntity:
    return CompanyEntity(name="Acme Corp Ltd", jurisdiction="GB", registration_number="12345678")


def _make_risk_rating(level="Green", score=20) -> RiskRating:
    return RiskRating(level=level, score=score, summary="Test summary")


# ── CompanyEntity ──────────────────────────────────────────────────────────────

def test_company_entity_minimal():
    entity = _make_entity()
    assert entity.name == "Acme Corp Ltd"
    assert entity.jurisdiction == "GB"


def test_company_entity_is_frozen():
    entity = _make_entity()
    with pytest.raises(ValidationError):
        entity.name = "changed"  # type: ignore[misc]


# ── RiskRating ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("level,score", [("Green", 0), ("Green", 33), ("Amber", 34), ("Amber", 66), ("Red", 67), ("Red", 100)])
def test_risk_rating_valid_combos(level, score):
    rating = RiskRating(level=level, score=score, summary="ok")
    assert rating.level == level


@pytest.mark.parametrize("level,score", [("Green", 34), ("Amber", 33), ("Amber", 67), ("Red", 66)])
def test_risk_rating_invalid_combos(level, score):
    with pytest.raises(ValidationError):
        RiskRating(level=level, score=score, summary="bad")


def test_risk_rating_case_normalisation():
    rating = RiskRating(level="green", score=10, summary="ok")  # type: ignore[arg-type]
    assert rating.level == "Green"


# ── SanctionsHit ──────────────────────────────────────────────────────────────

def test_sanctions_hit_score_rounded():
    hit = SanctionsHit(list_name="OFAC SDN", matched_name="Acme Corp", match_score=0.912345678)
    assert hit.match_score == 0.9123


# ── KYCReport helpers ─────────────────────────────────────────────────────────

def _build_full_report(level="Green", score=10) -> KYCReport:
    entity = _make_entity()
    research = ResearchFindings(summary="Nothing notable", sources=["https://example.com"])
    sanctions = SanctionsResults(screened_name=entity.name, is_sanctioned=False, checked_lists=["OFAC"])
    ubo = UBOStructure(subject_name=entity.name, ubos=[], ownership_verified=True)
    risk = RiskRating(level=level, score=score, summary="Low risk")
    return KYCReport(
        entity=entity,
        research_findings=research,
        sanctions_results=sanctions,
        ubo_structure=ubo,
        risk_rating=risk,
    )


def test_kyc_report_is_high_risk_false():
    assert not _build_full_report("Green", 10).is_high_risk()


def test_kyc_report_is_high_risk_true():
    assert _build_full_report("Red", 80).is_high_risk()


def test_kyc_report_requires_review_amber():
    assert _build_full_report("Amber", 50).requires_review()


def test_kyc_report_requires_review_with_flags():
    report = _build_full_report("Green", 10)
    flagged = report.model_copy(update={"flags": ["PEP IDENTIFIED: John Doe"]})
    assert flagged.requires_review()
