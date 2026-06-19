from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.auth import Principal, ReviewerDirectory
from handoff.config import Settings
from handoff.errors import AuthenticationError
from handoff.events.broker import EventBroker
from handoff.services.approvals import ApprovalService
from handoff.services.runs import RunService

SESSION_COOKIE = "handoff_session"


@dataclass(frozen=True)
class Container:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    runs: RunService
    approvals: ApprovalService
    broker: EventBroker
    reviewers: ReviewerDirectory


def container(request: Request) -> Container:
    value: Container = request.app.state.container
    return value


def run_service(c: Annotated[Container, Depends(container)]) -> RunService:
    return c.runs


def approval_service(c: Annotated[Container, Depends(container)]) -> ApprovalService:
    return c.approvals


_bearer = HTTPBearer(auto_error=False)


def current_reviewer(
    request: Request,
    c: Annotated[Container, Depends(container)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """Bearer token for API clients; an HttpOnly cookie for the browser, since EventSource
    cannot send an Authorization header."""
    token = credentials.credentials if credentials else request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthenticationError("Sign in to continue.")
    principal = c.reviewers.authenticate(token)
    if principal is None:
        raise AuthenticationError("Your session is not valid. Sign in again.")
    return principal


ContainerDep = Annotated[Container, Depends(container)]
RunServiceDep = Annotated[RunService, Depends(run_service)]
ApprovalServiceDep = Annotated[ApprovalService, Depends(approval_service)]
ReviewerDep = Annotated[Principal, Depends(current_reviewer)]
