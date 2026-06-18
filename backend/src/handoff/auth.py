from __future__ import annotations

import hmac
from collections.abc import Sequence

from pydantic import BaseModel

from handoff.config import ReviewerAccount


class Principal(BaseModel):
    """An authenticated reviewer. `tier` is the index of their role in the escalation tiers."""

    name: str
    role: str
    tier: int


class DemoAccount(BaseModel):
    name: str
    role: str
    token: str


class ReviewerDirectory:
    """Static reviewer accounts from settings, looked up by bearer token."""

    def __init__(self, accounts: Sequence[ReviewerAccount], tiers: Sequence[str]) -> None:
        self._accounts = list(accounts)
        self._tiers = list(tiers)

    @property
    def top_tier(self) -> int:
        return len(self._tiers) - 1

    def tier_of(self, role: str) -> int:
        return self._tiers.index(role)

    def authenticate(self, token: str) -> Principal | None:
        candidate = token.encode()
        found: ReviewerAccount | None = None
        for account in self._accounts:
            # Compare against every account so timing does not reveal which prefix matched.
            if hmac.compare_digest(account.token.get_secret_value().encode(), candidate):
                found = account
        if found is None:
            return None
        return Principal(name=found.name, role=found.role, tier=self.tier_of(found.role))

    def demo_accounts(self) -> list[DemoAccount]:
        return [
            DemoAccount(name=a.name, role=a.role, token=a.token.get_secret_value()) for a in self._accounts
        ]
