"""The HTTP layer around explain_stream."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from app import providers as provider_module
from app.budget import DailyBudget, estimate_cost_usd
from app.providers import LLMProvider
from app.stream import explain_stream


@dataclass
class StreamSettings:
    ttft_timeout_s: float = 2.0
    total_timeout_s: float = 20.0
    max_output_tokens: int = 400


class ExplainRequest(BaseModel):
    clause_text: str = Field(min_length=1, max_length=8000)
    language: Literal["ar", "en"]


class BudgetExhausted(Exception):
    pass


def create_app(
    providers: Sequence[LLMProvider],
    budget: DailyBudget,
    settings: StreamSettings | None = None,
) -> FastAPI:
    settings = settings or StreamSettings()
    app = FastAPI()

    @app.exception_handler(BudgetExhausted)
    async def budget_exhausted_handler(
        request: Request,
        exc: BudgetExhausted,
    ):
        return JSONResponse(
            status_code=429,
            media_type="application/problem+json",
            content={
                "type": "/problems/budget-exhausted",
                "title": "Daily AI budget exhausted",
                "status": 429,
            },
        )

    async def prepare_request(
        body: ExplainRequest,
        tenant: str = Header(
            ...,
            alias="X-Tenant-ID",
            min_length=1,
            max_length=64,
        ),
    ) -> tuple[str, str]:
        prompt = provider_module.build_prompt(
            body.clause_text,
            body.language,
        )

        if not providers:
            raise BudgetExhausted()

        cheapest_cost = min(
            estimate_cost_usd(
                provider,
                prompt,
                settings.max_output_tokens,
            )
            for provider in providers
        )

        if cheapest_cost > budget.remaining(tenant):
            raise BudgetExhausted()

        return prompt, tenant

    @app.post(
        "/v1/clauses/explain",
        response_class=EventSourceResponse,
    )
    async def explain_clause(
        prepared: tuple[str, str] = Depends(prepare_request),
    ) -> AsyncIterator[ServerSentEvent]:
        prompt, tenant = prepared

        async for event in explain_stream(
            prompt,
            providers,
            tenant=tenant,
            budget=budget,
            ttft_timeout_s=settings.ttft_timeout_s,
            total_timeout_s=settings.total_timeout_s,
            max_output_tokens=settings.max_output_tokens,
        ):
            yield ServerSentEvent(
                event=event.kind,
                data=event.data,
            )

    return app
