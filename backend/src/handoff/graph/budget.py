from __future__ import annotations

from dataclasses import dataclass, field

from handoff.errors import BudgetExceeded
from handoff.graph.state import Budget, Usage
from handoff.llm.pricing import price_for
from handoff.llm.types import TokenUsage


@dataclass
class SpendLedger:
    """Everything a run has spent, including attempts that failed, were retried or died in a crash.

    Graph state only accumulates usage from node attempts that succeed, so it cannot be the
    number the cap is enforced against. The worker seeds the ledger from the run row, which
    every `llm.call` event increments, and every guard in the run records into it.
    """

    usage: Usage = field(default_factory=Usage)

    def record(self, step: Usage) -> None:
        self.usage = self.usage + step


class BudgetGuard:
    """Tracks one node attempt's spend and enforces the run's cap against the full ledger."""

    def __init__(self, budget: Budget, spent: Usage, ledger: SpendLedger | None = None) -> None:
        self._budget = budget
        self._spent = spent
        self._ledger = ledger or SpendLedger(usage=spent)
        self.delta = Usage()

    @property
    def total(self) -> Usage:
        from_state = self._spent + self.delta
        ledger = self._ledger.usage
        return Usage(
            input_tokens=max(from_state.input_tokens, ledger.input_tokens),
            output_tokens=max(from_state.output_tokens, ledger.output_tokens),
            cost_usd=max(from_state.cost_usd, ledger.cost_usd),
            llm_calls=max(from_state.llm_calls, ledger.llm_calls),
            tool_calls=max(from_state.tool_calls, ledger.tool_calls),
        )

    def ensure_headroom(self) -> None:
        total = self.total
        if total.total_tokens >= self._budget.max_tokens:
            raise BudgetExceeded(
                f"Token budget exhausted ({total.total_tokens:,} of {self._budget.max_tokens:,})",
                details={"tokens": total.total_tokens, "max_tokens": self._budget.max_tokens},
            )
        if total.cost_usd >= self._budget.max_usd:
            raise BudgetExceeded(
                f"Spend cap reached (${total.cost_usd:.4f} of ${self._budget.max_usd:.2f})",
                details={"cost_usd": round(total.cost_usd, 6), "max_usd": self._budget.max_usd},
            )

    def output_cap(self, requested: int) -> int:
        remaining = self._budget.max_tokens - self.total.total_tokens
        return max(256, min(requested, remaining))

    def record_llm(self, model: str, usage: TokenUsage) -> Usage:
        step = Usage(
            input_tokens=usage.billable_input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(price_for(model).cost(usage), 6),
            llm_calls=1,
        )
        self.delta = self.delta + step
        self._ledger.record(step)
        return step

    def record_tool(self) -> None:
        step = Usage(tool_calls=1)
        self.delta = self.delta + step
        self._ledger.record(step)
