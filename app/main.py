"""The HTTP layer around explain_stream.

Keep `StreamSettings` and `create_app` exactly as named; the public and hidden tests import
them."""
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import FastAPI

from app.budget import DailyBudget
from app.providers import LLMProvider


@dataclass
class StreamSettings:
    ttft_timeout_s: float = 2.0
    total_timeout_s: float = 20.0
    max_output_tokens: int = 400


def create_app(providers: Sequence[LLMProvider], budget: DailyBudget,
               settings: StreamSettings | None = None) -> FastAPI:
    """Return a NEW FastAPI app exposing POST /v1/clauses/explain.

    - Header X-Tenant-ID (required, 1-64 chars). Body {"clause_text": 1-8000 chars,
      "language": "ar" | "en"}. Build the prompt with app.providers.build_prompt.
    - Before streaming: invalid input is 422; if the tenant cannot afford even the
      cheapest provider's worst-case estimate, 429 application/problem+json with type
      /problems/budget-exhausted. Providers are not called in either case.
    - Otherwise, a text/event-stream response (use fastapi.sse.EventSourceResponse and
      ServerSentEvent) whose events are explain_stream's events, named meta, token, done
      and error, each event's data as JSON.
    """
    raise NotImplementedError
