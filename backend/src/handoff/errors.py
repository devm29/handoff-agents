"""Error taxonomy shared by the graph, the worker and the API.

Every failure that can end or degrade a run maps onto one of four kinds. The kind
decides whether the node retry policy is allowed to try again, and it is what the
UI shows next to a failed step.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

ErrorKind = Literal["ToolError", "ModelError", "PolicyViolation", "BudgetExceeded", "InternalError"]


class ErrorInfo(BaseModel):
    kind: ErrorKind
    message: str
    node: str | None = None
    retryable: bool = False
    attempt: int | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HandoffError(Exception):
    kind: ErrorKind = "InternalError"
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, str | int | float | bool | None] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_info(self, *, node: str | None = None, attempt: int | None = None) -> ErrorInfo:
        return ErrorInfo(
            kind=self.kind,
            message=self.message,
            node=node,
            retryable=self.retryable,
            attempt=attempt,
            details=self.details,
        )


class ToolError(HandoffError):
    """The tool transport failed. Tool-level errors the model can react to are not raised."""

    kind = "ToolError"
    retryable = True


class ModelError(HandoffError):
    kind = "ModelError"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        details: dict[str, str | int | float | bool | None] | None = None,
    ):
        super().__init__(message, details=details)
        self.retryable = retryable


class PolicyViolation(HandoffError):
    kind = "PolicyViolation"
    retryable = False


class BudgetExceeded(HandoffError):
    kind = "BudgetExceeded"
    retryable = False


class NotFoundError(Exception):
    def __init__(self, resource: str, identifier: str):
        super().__init__(f"{resource} {identifier} not found")
        self.resource = resource
        self.identifier = identifier


class ConflictError(Exception):
    pass


class BadRequestError(Exception):
    pass


class UnprocessableError(Exception):
    """The request is well-formed but a business rule refuses it."""


class AuthenticationError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class LeaseLost(Exception):
    """This worker no longer owns the run: another worker reclaimed it after the lease went stale."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"lease on run {run_id} was lost")
        self.run_id = run_id


def classify(exc: BaseException, *, node: str | None = None, attempt: int | None = None) -> ErrorInfo:
    if isinstance(exc, HandoffError):
        return exc.to_info(node=node, attempt=attempt)
    return ErrorInfo(kind="InternalError", message=f"{type(exc).__name__}: {exc}", node=node, attempt=attempt)
