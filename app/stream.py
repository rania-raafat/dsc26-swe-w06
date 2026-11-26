"""The streaming core: provider fallback, two deadlines, budget reserve/settle."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from app.budget import DailyBudget, actual_cost_usd, estimate_cost_usd
from app.providers import LLMProvider, ProviderError


@dataclass(frozen=True)
class Event:
    kind: str
    data: dict = field(default_factory=dict)


async def explain_stream(
    prompt: str,
    providers: Sequence[LLMProvider],
    *,
    tenant: str,
    budget: DailyBudget,
    ttft_timeout_s: float,
    total_timeout_s: float,
    max_output_tokens: int,
) -> AsyncIterator[Event]:

    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_timeout_s
    affordable_attempts = 0

    for provider in providers:
        reserved = estimate_cost_usd(
            provider,
            prompt,
            max_output_tokens,
        )

        if not budget.try_reserve(tenant, reserved):
            continue

        affordable_attempts += 1
        produced_tokens = 0
        terminal_error = None
        succeeded = False
        stream = None

        try:
            stream = provider.stream(prompt, max_output_tokens)

            remaining = deadline - loop.time()

            if remaining <= 0:
                terminal_error = {
                    "code": "deadline_exceeded",
                    "partial": False,
                }

            else:
                first_wait = min(ttft_timeout_s, remaining)

                try:
                    first_token = await asyncio.wait_for(
                        anext(stream),
                        timeout=first_wait,
                    )

                except StopAsyncIteration:
                    first_token = None

                    if loop.time() >= deadline:
                        terminal_error = {
                            "code": "deadline_exceeded",
                            "partial": False,
                        }

                except ProviderError:
                    first_token = None

                    if loop.time() >= deadline:
                        terminal_error = {
                            "code": "deadline_exceeded",
                            "partial": False,
                        }

                except TimeoutError:
                    first_token = None

                    if loop.time() >= deadline:
                        terminal_error = {
                            "code": "deadline_exceeded",
                            "partial": False,
                        }

                if first_token is not None:
                    produced_tokens += 1

                    yield Event(
                        "meta",
                        {"provider": provider.name},
                    )

                    yield Event(
                        "token",
                        {"text": first_token},
                    )

                    while True:
                        remaining = deadline - loop.time()

                        if remaining <= 0:
                            terminal_error = {
                                "code": "deadline_exceeded",
                                "partial": True,
                            }
                            break

                        try:
                            token = await asyncio.wait_for(
                                anext(stream),
                                timeout=remaining,
                            )

                        except StopAsyncIteration:
                            succeeded = True
                            break

                        except ProviderError:
                            terminal_error = {
                                "code": "upstream_interrupted",
                                "partial": True,
                            }
                            break

                        except TimeoutError:
                            terminal_error = {
                                "code": "deadline_exceeded",
                                "partial": True,
                            }
                            break

                        produced_tokens += 1

                        yield Event(
                            "token",
                            {"text": token},
                        )

        finally:
            try:
                if stream is not None:
                    close = getattr(stream, "aclose", None)

                    if close is not None:
                        await close()

            finally:
                actual = (
                    actual_cost_usd(
                        provider,
                        prompt,
                        produced_tokens,
                    )
                    if produced_tokens > 0
                    else 0.0
                )

                budget.settle(
                    tenant,
                    reserved,
                    actual,
                )

        if succeeded:
            actual = actual_cost_usd(
                provider,
                prompt,
                produced_tokens,
            )

            yield Event(
                "done",
                {
                    "provider": provider.name,
                    "output_tokens": produced_tokens,
                    "cost_usd": actual,
                },
            )

            return

        if terminal_error is not None:
            yield Event("error", terminal_error)
            return

        # No first token: try the next provider.

    if affordable_attempts == 0:
        yield Event(
            "error",
            {"code": "budget_exhausted"},
        )

    else:
        yield Event(
            "error",
            {"code": "all_providers_failed"},
        )
