"""Provided by DSC. Do not edit: the grader replaces this file with its own copy
(different token lists, prices, delays and provider names from these). Use it to test
your code by hand; no network call and no API key are ever involved."""
import asyncio
from collections.abc import AsyncIterator

from app.providers import ProviderError


class FakeProvider:
    def __init__(self, name: str, tokens: list[str] | None = None, *,
                 price_in_per_mtok: float = 1.0, price_out_per_mtok: float = 5.0,
                 first_token_delay: float = 0.0, token_delay: float = 0.0,
                 fail_before_first: bool = False, fail_after_tokens: int | None = None,
                 hang: bool = False):
        self.name = name
        self.tokens = tokens if tokens is not None else ["This ", "clause ", "caps ", "liability."]
        self.price_in_per_mtok, self.price_out_per_mtok = price_in_per_mtok, price_out_per_mtok
        self.first_token_delay, self.token_delay = first_token_delay, token_delay
        self.fail_before_first, self.fail_after_tokens, self.hang = fail_before_first, fail_after_tokens, hang
        self.calls = 0
        self.closed = 0      # how many streams were closed (finished, failed, cancelled or aclose()d)
        self.emitted = 0     # tokens actually produced across all calls

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    async def stream(self, prompt: str, max_output_tokens: int) -> AsyncIterator[str]:
        self.calls += 1
        try:
            if self.hang:
                await asyncio.sleep(3600)
            await asyncio.sleep(self.first_token_delay)
            if self.fail_before_first:
                raise ProviderError(f"{self.name}: overloaded")
            for i, tok in enumerate(self.tokens[:max_output_tokens]):
                if self.fail_after_tokens is not None and i == self.fail_after_tokens:
                    raise ProviderError(f"{self.name}: connection reset")
                if i:
                    await asyncio.sleep(self.token_delay)
                self.emitted += 1
                yield tok
        finally:
            self.closed += 1
