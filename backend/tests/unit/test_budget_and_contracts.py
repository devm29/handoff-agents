from __future__ import annotations

import pytest

from handoff.agents.schemas import ResearchFindings, VendorProfile
from handoff.errors import BudgetExceeded, PolicyViolation
from handoff.graph.budget import BudgetGuard
from handoff.graph.contracts import RiskAnalystInput, build_input, validate_handoff
from handoff.graph.state import Budget, DueDiligenceState, Usage
from handoff.llm.types import TokenUsage


def _state(**extra: object) -> DueDiligenceState:
    return DueDiligenceState.model_validate(
        {"vendor": {"name": "Acme Corp", "country": "us"}, "budget": {"max_tokens": 10_000, "max_usd": 0.1}}
        | extra
    )


def _research() -> ResearchFindings:
    return ResearchFindings(
        legal_name="Acme Corp",
        registration_number="1",
        jurisdiction="US",
        status="active",
        incorporated_on=None,
        industry=None,
        address=None,
        summary="ok",
    )


def test_vendor_country_is_normalised() -> None:
    assert _state().vendor.country == "US"


def test_guard_records_cost_and_blocks_further_calls() -> None:
    guard = BudgetGuard(Budget(max_tokens=10_000, max_usd=0.05), Usage())
    step = guard.record_llm("claude-opus-5-5", TokenUsage(input_tokens=5_000, output_tokens=2_000))
    assert step.cost_usd == pytest.approx(0.06)
    with pytest.raises(BudgetExceeded, match="Spend cap"):
        guard.ensure_headroom()


def test_guard_counts_prior_spend_and_caps_output() -> None:
    guard = BudgetGuard(Budget(max_tokens=10_000, max_usd=5), Usage(input_tokens=9_000))
    assert guard.output_cap(8_000) == 1_000
    guard.record_llm("claude-opus-5-5", TokenUsage(input_tokens=900, output_tokens=200))
    with pytest.raises(BudgetExceeded, match="Token budget"):
        guard.ensure_headroom()


def test_handoff_requires_prerequisites() -> None:
    with pytest.raises(PolicyViolation, match="research is not available"):
        build_input("risk_analyst", _state())
    payload = build_input("risk_analyst", _state(research=_research()))
    assert isinstance(payload, RiskAnalystInput)


def test_repeating_a_completed_step_is_a_violation() -> None:
    with pytest.raises(PolicyViolation, match="already completed"):
        validate_handoff("researcher", _state(research=_research()))


def test_finish_requires_report() -> None:
    with pytest.raises(PolicyViolation, match="final report"):
        validate_handoff("finish", _state())


def test_invalid_vendor_rejected() -> None:
    with pytest.raises(ValueError, match="country"):
        VendorProfile(name="Acme", country="USA")
