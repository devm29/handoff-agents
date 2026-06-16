from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter

from handoff.agents.schemas import RiskLevel, RouteTarget, ScreeningResult, VendorProfile
from handoff.graph.state import ApprovalDecision

SCENARIO_DIR = Path(__file__).parent / "scenarios"


class Expectation(BaseModel):
    handoffs: list[RouteTarget]
    tools: dict[str, list[str]]
    risk_rating: RiskLevel
    compliance_status: ScreeningResult
    decision: str
    requires_human: bool


class Scenario(BaseModel):
    id: str
    description: str
    vendor: VendorProfile
    reviewer: ApprovalDecision | None = Field(default=None, description="Decision a human gives at the gate")
    expected: Expectation


def available_suites() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


def load_suite(name: str) -> list[Scenario]:
    path = SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown suite '{name}'. Available: {', '.join(available_suites())}")
    return TypeAdapter(list[Scenario]).validate_json(path.read_bytes())
