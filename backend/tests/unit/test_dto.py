from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from handoff.agents.schemas import VendorProfile
from handoff.auth import Principal
from handoff.errors import BadRequestError
from handoff.graph.state import ApprovalEdits, Budget, DueDiligenceState
from handoff.services.dto import DecisionRequest, StatePatch, decode_cursor, encode_cursor


def test_edit_decision_requires_edits() -> None:
    with pytest.raises(ValidationError, match="edits are required"):
        DecisionRequest(action="edit")
    with pytest.raises(ValidationError, match="only allowed"):
        DecisionRequest(action="approve", edits=ApprovalEdits(conditions=["x"]))
    reviewer = Principal(name="Sam Lee", role="analyst", tier=0)
    decision = DecisionRequest(
        action="edit", comment="  ", edits=ApprovalEdits(risk_rating="medium")
    ).to_decision(reviewer)
    assert decision.edits is not None
    assert (decision.reviewer, decision.reviewer_role) == ("Sam Lee", "analyst")
    assert decision.comment is None
    assert not decision.automatic


def test_reviewer_cannot_be_supplied_by_the_client() -> None:
    with pytest.raises(ValidationError, match="reviewer"):
        DecisionRequest.model_validate({"action": "approve", "reviewer": "Somebody Else"})


def test_cursor_round_trip_and_rejects_garbage() -> None:
    created, run_id = datetime(2026, 5, 1, 12, tzinfo=UTC), uuid4()
    assert decode_cursor(encode_cursor(created, run_id)) == (created, run_id)
    with pytest.raises(BadRequestError, match="invalid cursor"):
        decode_cursor("not-a-cursor")


def test_state_patch_only_touches_given_fields() -> None:
    state = DueDiligenceState(
        vendor=VendorProfile(name="Acme", country="US"), budget=Budget(max_tokens=10, max_usd=1)
    )
    patched = StatePatch(budget=Budget(max_tokens=99, max_usd=2)).apply(state)
    assert patched.budget.max_tokens == 99
    assert patched.vendor == state.vendor


def test_state_patch_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        StatePatch.model_validate({"report": {}})
