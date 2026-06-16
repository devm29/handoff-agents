from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import update

from handoff.api.sse import run_event_stream
from handoff.db.models import ApprovalRow, RunRow
from handoff.db.repositories import EventRepository, RunRepository
from handoff.events.broker import EventBroker

from .conftest import COMPLIANCE_LEAD, CRO, WORKER_ID, Stack

pytestmark = pytest.mark.postgres


async def _create(stack: Stack, name: str, country: str, **extra: Any) -> str:
    response = await stack.client.post("/runs", json={"vendor": {"name": name, "country": country}} | extra)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _run(stack: Stack, run_id: str) -> dict[str, Any]:
    response = await stack.client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    return dict(response.json())


async def test_approval_lifecycle_through_the_api(stack: Stack) -> None:
    run_id = await _create(stack, "Helios Components", "GB")
    await stack.work()

    run = await _run(stack, run_id)
    assert run["status"] == "awaiting_approval"
    assert run["usage"]["llm_calls"] > 0
    inbox = (await stack.client.get("/approvals", params={"status": "pending"})).json()["items"]
    assert [a["run_id"] for a in inbox] == [run_id]
    approval = inbox[0]
    assert approval["request"]["recommendation"] == "approve_with_conditions"
    assert approval["assignee"] == "analyst"

    decision = {"action": "edit", "edits": {"conditions": ["Pen test report in 30 days"]}}
    response = await stack.client.post(f"/approvals/{approval['id']}/decision", json=decision)
    assert response.status_code == 200
    assert response.json()["decided_by"] == "Priya Raman", "the reviewer is the signed-in principal"
    assert response.json()["decision"]["reviewer_role"] == "analyst"
    again = await stack.client.post(f"/approvals/{approval['id']}/decision", json={"action": "approve"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"

    await stack.work()
    run = await _run(stack, run_id)
    assert run["status"] == "completed"
    assert run["decision"] == "approved_with_conditions"
    assert run["report"]["conditions"] == ["Pen test report in 30 days"]

    checkpoints = (await stack.client.get(f"/runs/{run_id}/checkpoints")).json()
    assert [c["step"] for c in checkpoints] == list(range(-1, len(checkpoints) - 1))
    assert any(c["interrupted"] and c["next"] == ["approval"] for c in checkpoints)
    events = (await stack.client.get(f"/runs/{run_id}/events/history")).json()
    kinds = {e["type"] for e in events}
    assert {"approval.requested", "approval.decided", "handoff", "tool.call", "llm.call"} <= kinds


async def test_worker_crash_resumes_from_last_checkpoint(stack: Stack) -> None:
    run_id = UUID(await _create(stack, "Atlas Cloud Services", "US"))
    async with stack.sessions.begin() as session:
        claimed = await RunRepository(session).claim_next(WORKER_ID, timedelta(seconds=30))
    assert claimed is not None and claimed.id == run_id and claimed.claims == 1

    task = asyncio.create_task(stack.executor.execute(run_id, fence=claimed.claims))
    while len(await stack.runs.checkpoints(run_id)) < 6:
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    checkpoints_at_crash = len(await stack.runs.checkpoints(run_id))
    assert (await _run(stack, str(run_id)))["status"] == "running"

    async with stack.sessions.begin() as session:
        assert await RunRepository(session).claim_next("other-worker", timedelta(seconds=30)) is None, (
            "a live lease is respected"
        )
        await session.execute(update(RunRow).values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=5)))
    async with stack.sessions.begin() as session:
        reclaimed = await RunRepository(session).claim_next("other-worker", timedelta(seconds=30))
    assert reclaimed is not None and reclaimed.id == run_id and reclaimed.claims == 2

    async with stack.sessions.begin() as session:
        stale_write = await RunRepository(session).transition(run_id, "failed", fence=claimed.claims)
    assert not stale_write, "the worker that lost the lease cannot overwrite the run"
    await stack.executor.execute(run_id, fence=claimed.claims)
    assert (await _run(stack, str(run_id)))["status"] == "running", "a stale executor is a no-op"

    await stack.executor.execute(run_id, fence=reclaimed.claims)
    run = await _run(stack, str(run_id))
    assert run["status"] == "completed"
    assert run["claims"] == 2
    assert len(await stack.runs.checkpoints(run_id)) > checkpoints_at_crash
    async with stack.sessions() as session:
        completed = dict(await EventRepository(session).count_by_type(run_id, "node.completed"))
    assert completed["researcher"] == 1, "work finished before the crash is not repeated"


async def test_api_requires_a_signed_in_reviewer(stack: Stack) -> None:
    anonymous = {"Authorization": ""}
    assert (await stack.client.get("/runs", headers=anonymous)).status_code == 401
    assert (await stack.client.post("/runs", json={}, headers=anonymous)).status_code == 401
    assert (await stack.client.get("/healthz", headers=anonymous)).status_code == 200
    bad = await stack.client.get("/runs", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "unauthenticated"

    signed_in = await stack.client.post("/session", json={"token": "demo-cro-token"}, headers=anonymous)
    assert signed_in.status_code == 200
    assert signed_in.json() == {
        "name": "James Whitaker",
        "role": "chief-risk-officer",
        "tier": 2,
        "top_tier": True,
    }
    cookie = signed_in.cookies.get("handoff_session")
    assert cookie == "demo-cro-token"
    stack.client.cookies.clear()
    who = await stack.client.get("/session", headers=anonymous | {"Cookie": f"handoff_session={cookie}"})
    assert who.json()["name"] == "James Whitaker"
    assert (await stack.client.get("/session/demo-accounts")).json() == [], "demo accounts are dev-only"


async def test_confirmed_sanctions_match_cannot_be_waved_through(stack: Stack) -> None:
    run_id = await _create(stack, "Corvane Trading", "AE")
    await stack.work()
    approval = (await stack.client.get("/approvals", params={"status": "pending"})).json()["items"][0]
    assert approval["run_id"] == run_id
    assert approval["request"]["compliance_status"] == "match"
    url = f"/approvals/{approval['id']}/decision"

    analyst = await stack.client.post(url, json={"action": "approve"})
    assert analyst.status_code == 403
    lead = await stack.client.post(url, json={"action": "approve", "comment": "ok"}, headers=COMPLIANCE_LEAD)
    assert lead.status_code == 403
    unjustified = await stack.client.post(url, json={"action": "approve"}, headers=CRO)
    assert unjustified.status_code == 422
    assert unjustified.json()["error"]["code"] == "refused"

    rejected = await stack.client.post(url, json={"action": "reject", "comment": "SDN owner"})
    assert rejected.status_code == 200
    await stack.work()
    assert (await _run(stack, run_id))["status"] == "rejected"


async def test_unanswered_approval_escalates_then_expires(stack: Stack) -> None:
    run_id = await _create(stack, "Corvane Trading", "AE")
    await stack.work()

    async def expire_deadline() -> None:
        async with stack.sessions.begin() as session:
            await session.execute(update(ApprovalRow).values(due_at=datetime.now(UTC) - timedelta(seconds=1)))

    for expected_assignee in ("compliance-lead", "chief-risk-officer"):
        await expire_deadline()
        assert await stack.approvals.sweep_overdue() == 1
        approval = (await stack.client.get("/approvals")).json()["items"][0]
        assert approval["assignee"] == expected_assignee
        assert approval["status"] == "pending"

    too_junior = await stack.client.post(f"/approvals/{approval['id']}/decision", json={"action": "reject"})
    assert too_junior.status_code == 403, "an escalated approval is out of the analyst's reach"

    await expire_deadline()
    await stack.approvals.sweep_overdue()
    approval = (await stack.client.get("/approvals")).json()["items"][0]
    assert approval["status"] == "expired"
    assert approval["decision"]["reviewer"] == "policy:timeout"

    await stack.work()
    run = await _run(stack, run_id)
    assert run["status"] == "rejected"
    assert run["report"]["decision"] == "rejected"


async def test_fork_from_checkpoint_with_edited_state(stack: Stack) -> None:
    source = await _create(stack, "Kestrel Microsystems", "SG")
    await stack.work()
    checkpoints = (await stack.client.get(f"/runs/{source}/checkpoints")).json()
    after_compliance = next(c for c in checkpoints if c["produced_by"] == "compliance_checker")

    detail = (
        await stack.client.get(f"/runs/{source}/checkpoints/{after_compliance['checkpoint_id']}")
    ).json()
    risk = detail["state"]["risk"] | {"rating": "low", "score": 5, "factors": []}
    response = await stack.client.post(
        f"/runs/{source}/fork",
        json={"checkpoint_id": after_compliance["checkpoint_id"], "state_patch": {"risk": risk}},
    )
    assert response.status_code == 201, response.text
    fork = response.json()
    assert fork["parent_run_id"] == source
    assert fork["usage"]["llm_calls"] > 0, "spend up to the fork point is inherited"

    await stack.work()
    forked = await _run(stack, fork["id"])
    assert forked["status"] == "completed"
    assert forked["state"]["approval"]["automatic"] is True
    assert (await _run(stack, source))["status"] == "awaiting_approval"

    bad = await stack.client.post(
        f"/runs/{source}/fork",
        json={
            "checkpoint_id": after_compliance["checkpoint_id"],
            "state_patch": {"budget": {"max_tokens": -1}},
        },
    )
    assert bad.status_code == 422


async def test_budget_failure_is_recorded_with_its_kind(stack: Stack) -> None:
    run_id = await _create(stack, "Meridian Pharma", "ES", budget={"max_tokens": 50_000, "max_usd": 0.03})
    await stack.work()
    run = await _run(stack, run_id)
    assert run["status"] == "failed"
    assert run["error"]["kind"] == "BudgetExceeded"
    assert run["usage"]["cost_usd"] >= 0.03


async def test_cancel_and_validation_errors(stack: Stack) -> None:
    run_id = await _create(stack, "Orion Freight", "US")
    cancelled = await stack.client.post(f"/runs/{run_id}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert (await stack.client.post(f"/runs/{run_id}/cancel")).status_code == 409
    missing = "/runs/00000000-0000-0000-0000-000000000000"
    assert (await stack.client.get(missing)).status_code == 404
    assert (await stack.client.get(f"{missing}/events/history")).status_code == 404
    assert (await stack.client.get("/runs", params={"cursor": "garbage"})).status_code == 400
    invalid = await stack.client.post("/runs", json={"vendor": {"name": "X", "country": "Germany"}})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert "vendor.country" in invalid.json()["error"]["message"]


async def test_run_listing_paginates_with_cursor(stack: Stack) -> None:
    for name in ("Northwind Logistics", "Atlas Cloud Services", "Lumen Health Partners"):
        await _create(stack, name, "US")
    first = (await stack.client.get("/runs", params={"limit": 2})).json()
    second = (await stack.client.get("/runs", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert second["next_cursor"] is None
    names = [r["vendor_name"] for r in first["items"] + second["items"]]
    assert names == ["Lumen Health Partners", "Atlas Cloud Services", "Northwind Logistics"]
    filtered = (await stack.client.get("/runs", params={"q": "atlas"})).json()["items"]
    assert [r["vendor_name"] for r in filtered] == ["Atlas Cloud Services"]


async def test_event_stream_replays_then_follows_live_events(stack: Stack, settings: Any) -> None:
    run_id = UUID(await _create(stack, "Northwind Logistics", "DE"))
    broker = EventBroker(settings.psycopg_url)
    await broker.start()
    await asyncio.wait_for(broker.connected.wait(), timeout=5)
    stream = run_event_stream(run_id, 0, broker, stack.sessions)
    try:
        first = await asyncio.wait_for(anext(stream), timeout=5)
        assert first["event"] == "run.status"

        worker = asyncio.create_task(stack.work())
        seen = [first]
        while seen[-1]["event"] != "run.status" or '"completed"' not in seen[-1]["data"]:
            seen.append(await asyncio.wait_for(anext(stream), timeout=10))
        await worker
        ids = [int(frame["id"]) for frame in seen]
        assert ids == sorted(set(ids)), "no duplicates, strictly ordered"
        assert any(frame["event"] == "node.started" for frame in seen)
    finally:
        await stream.aclose()
        await broker.stop()
