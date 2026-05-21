from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CompanyEntity(BaseModel):
    """The subject of a KYC screening request."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Registered legal name of the company")
    jurisdiction: str = Field(..., description="Country / jurisdiction of incorporation (ISO-3166 alpha-2 preferred)")
    registration_number: Optional[str] = Field(None, description="Company registration / incorporation number")
    address: Optional[str] = Field(None, description="Registered address")
    website: Optional[str] = Field(None, description="Primary website URL")
    industry: Optional[str] = Field(None, description="Industry / sector description")


class PersonEntity(BaseModel):
    """Represents an individual relevant to a KYC screening (e.g. director, UBO)."""

    model_config = ConfigDict(frozen=True)

    name: str
    nationality: Optional[str] = Field(None, description="ISO-3166 alpha-2 country code")
    date_of_birth: Optional[str] = Field(None, description="YYYY-MM-DD format where known")
    id_number: Optional[str] = None
    role: Optional[str] = Field(None, description="Role in the subject company (e.g. Director, CEO)")
