"""Structured outputs produced by each specialist.

These models double as the JSON schemas of the `submit_*` tools the agents call to
finish their turn, so field descriptions are written for the model as much as for humans.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RiskLevel = Literal["low", "medium", "high", "critical"]
AgentName = Literal["researcher", "risk_analyst", "compliance_checker", "report_writer"]
RouteTarget = Literal[
    "researcher", "risk_analyst", "compliance_checker", "approval", "report_writer", "finish"
]
EvidenceSource = Literal["company_registry", "sanctions", "news"]
ScreeningResult = Literal["clear", "potential_match", "match"]
RiskCategory = Literal[
    "financial", "operational", "reputational", "legal", "cyber", "jurisdiction", "corporate"
]

RISK_ORDER: dict[RiskLevel, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class VendorProfile(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code")
    website: str | None = Field(default=None, max_length=300)
    registration_number: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("country")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class Evidence(BaseModel):
    source: EvidenceSource
    reference: str = Field(description="Identifier returned by the tool, e.g. a registry number or news id")
    summary: str


class BeneficialOwner(BaseModel):
    name: str
    role: str
    ownership_pct: float | None = Field(default=None, ge=0, le=100)
    nationality: str | None = None


class NewsItem(BaseModel):
    id: str
    published_on: date
    headline: str
    source: str
    sentiment: float = Field(ge=-1, le=1)
    topics: list[str] = Field(default_factory=list)


class ResearchFindings(BaseModel):
    legal_name: str
    registration_number: str | None
    jurisdiction: str
    status: Literal["active", "dissolved", "suspended", "unknown"]
    incorporated_on: date | None
    industry: str | None
    address: str | None
    beneficial_owners: list[BeneficialOwner] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)


class RiskFactor(BaseModel):
    category: RiskCategory
    description: str
    severity: RiskLevel
    evidence: list[str] = Field(default_factory=list, description="Evidence references backing this factor")


class RiskAssessment(BaseModel):
    rating: RiskLevel
    score: int = Field(ge=0, le=100)
    factors: list[RiskFactor] = Field(default_factory=list)
    rationale: str


class ScreeningHit(BaseModel):
    list_name: str
    matched_name: str
    score: float = Field(ge=0, le=1)
    program: str
    entry_id: str


class ScreenedEntity(BaseModel):
    name: str
    kind: Literal["company", "person"]
    result: ScreeningResult
    hits: list[ScreeningHit] = Field(default_factory=list)


class ComplianceResult(BaseModel):
    status: ScreeningResult
    screened: list[ScreenedEntity]
    notes: str


class ReportSection(BaseModel):
    title: str
    body: str


class DueDiligenceReport(BaseModel):
    title: str
    decision: Literal["approved", "approved_with_conditions", "rejected"]
    risk_rating: RiskLevel
    executive_summary: str
    sections: list[ReportSection]
    conditions: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class SupervisorDecision(BaseModel):
    next: RouteTarget
    task: str = Field(description="Instruction for the specialist receiving the handoff")
    rationale: str
