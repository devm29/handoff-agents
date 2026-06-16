from __future__ import annotations

from pydantic import BaseModel

from handoff.llm.types import TokenUsage

CACHE_WRITE_MULTIPLIER = 1.25


class ModelPrice(BaseModel):
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float

    def cost(self, usage: TokenUsage) -> float:
        return (
            usage.input_tokens * self.input_per_mtok
            + usage.cache_creation_input_tokens * self.input_per_mtok * CACHE_WRITE_MULTIPLIER
            + usage.cache_read_input_tokens * self.cache_read_per_mtok
            + usage.output_tokens * self.output_per_mtok
        ) / 1_000_000


# The scripted fake is priced like the default model so offline budgets behave like real ones.
PRICES: dict[str, ModelPrice] = {
    "claude-fable-5-1": ModelPrice(input_per_mtok=10.0, output_per_mtok=50.0, cache_read_per_mtok=0.25),
    "claude-opus-5-5": ModelPrice(input_per_mtok=4.0, output_per_mtok=20.0, cache_read_per_mtok=0.20),
    "claude-opus-5": ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0, cache_read_per_mtok=0.50),
    "claude-sonnet-5-5": ModelPrice(input_per_mtok=2.0, output_per_mtok=10.0, cache_read_per_mtok=0.20),
    "claude-haiku-4-5": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0, cache_read_per_mtok=0.10),
    "scripted-fake": ModelPrice(input_per_mtok=4.0, output_per_mtok=20.0, cache_read_per_mtok=0.20),
}

_FALLBACK = PRICES["claude-opus-5-5"]


def price_for(model: str) -> ModelPrice:
    return PRICES.get(model, _FALLBACK)
