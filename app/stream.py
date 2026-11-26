"""The streaming core: provider fallback, two deadlines, budget reserve/settle.

Keep `Event` and `explain_stream` exactly as named; the public and hidden tests import them."""
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from app.budget import DailyBudget
from app.providers import LLMProvider


@dataclass(frozen=True)
class Event:
    kind: str                       # "meta" | "token" | "done" | "error"
    data: dict = field(default_factory=dict)


async def explain_stream(prompt: str, providers: Sequence[LLMProvider], *, tenant: str,
                         budget: DailyBudget, ttft_timeout_s: float, total_timeout_s: float,
                         max_output_tokens: int) -> AsyncIterator[Event]:
    """Yield Event("meta", ...), Event("token", ...)* and a final Event("done" | "error", ...).

    Rules, in order (see README.md for the full statement):
    - Try providers in the given order. Before each, reserve its estimate; skip an
      unaffordable provider without calling it.
    - Wait at most ttft_timeout_s (never past the overall deadline) for the first token.
      On timeout, ProviderError, or an empty stream before the first token: settle the
      reservation at 0 and try the next provider.
    - On the first token, emit "meta" {"provider": name}, then "token" {"text": ...} per token.
    - After the first token, never switch provider: a ProviderError now is a fatal
      "error" {"code": "upstream_interrupted", "partial": True}.
    - The whole call never runs past total_timeout_s from the start; past the deadline, emit
      "error" {"code": "deadline_exceeded", "partial": <any token sent yet>}.
    - On success, settle at the actual cost and emit
      "done" {"provider", "output_tokens", "cost_usd"}.
    - Every affordable provider failed before its first token: "error" {"code": "all_providers_failed"}.
      No provider was affordable: "error" {"code": "budget_exhausted"}.
    - Whatever happens, including the caller closing this generator early, close the
      provider's stream (aclose()) and settle its reservation at the actual cost of the
      tokens it produced.
    """
    raise NotImplementedError
    yield  # pragma: no cover  (keeps this an async generator function)
