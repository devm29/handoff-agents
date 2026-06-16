from __future__ import annotations

from fastapi import APIRouter, Response, status

from handoff.api.deps import SESSION_COOKIE, ContainerDep, ReviewerDep
from handoff.auth import DemoAccount, Principal
from handoff.errors import AuthenticationError
from handoff.services.dto import SessionOut, SignInRequest

router = APIRouter(prefix="/session", tags=["session"])

SESSION_MAX_AGE = 12 * 3600


def _session_out(principal: Principal, c: ContainerDep) -> SessionOut:
    return SessionOut(
        name=principal.name,
        role=principal.role,
        tier=principal.tier,
        top_tier=principal.tier == c.reviewers.top_tier,
    )


@router.get("")
async def whoami(reviewer: ReviewerDep, c: ContainerDep) -> SessionOut:
    return _session_out(reviewer, c)


@router.post("")
async def sign_in(body: SignInRequest, response: Response, c: ContainerDep) -> SessionOut:
    principal = c.reviewers.authenticate(body.token)
    if principal is None:
        raise AuthenticationError("That access token is not recognised.")
    response.set_cookie(
        SESSION_COOKIE,
        body.token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=c.settings.session_cookie_secure,
        path="/",
    )
    return _session_out(principal, c)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(response: Response, c: ContainerDep) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=c.settings.session_cookie_secure
    )


@router.get("/demo-accounts")
async def demo_accounts(c: ContainerDep) -> list[DemoAccount]:
    """Lets the local demo offer one-click sign-in. Empty unless demo tokens are in use in development."""
    return c.reviewers.demo_accounts() if c.settings.demo_accounts_enabled else []
