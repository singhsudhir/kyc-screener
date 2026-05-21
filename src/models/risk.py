from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


RiskLevel = Literal["Green", "Amber", "Red"]


class RiskFactor(BaseModel):
    """A single factor contributing to the overall risk rating."""

    model_config = ConfigDict(frozen=True)

    category: str = Field(..., description="Category of risk factor, e.g. 'Sanctions', 'PEP', 'Adverse Media'")
    description: str
    weight: float = Field(..., ge=0.0, le=1.0, description="Relative weight of this factor (0–1)")


class RiskRating(BaseModel):
    """Overall risk rating assigned by the Risk Assessment Agent."""

    model_config = ConfigDict(frozen=True)

    level: RiskLevel
    score: int = Field(..., ge=0, le=100, description="Numeric risk score 0 (lowest) – 100 (highest)")
    factors: list[RiskFactor] = Field(default_factory=list)
    summary: str = Field(..., description="Short narrative explaining the rating")

    @field_validator("level", mode="before")
    @classmethod
    def normalise_level(cls, v: str) -> str:
        mapping = {"green": "Green", "amber": "Amber", "red": "Red"}
        return mapping.get(str(v).lower(), v)

    @field_validator("score")
    @classmethod
    def score_matches_level(cls, score: int, info) -> int:
        level = info.data.get("level")
        if level == "Green" and score > 33:
            raise ValueError(f"Score {score} is inconsistent with Green rating (must be ≤ 33)")
        if level == "Amber" and not (34 <= score <= 66):
            raise ValueError(f"Score {score} is inconsistent with Amber rating (must be 34–66)")
        if level == "Red" and score < 67:
            raise ValueError(f"Score {score} is inconsistent with Red rating (must be ≥ 67)")
        return score
