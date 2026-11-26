"""Provided by DSC. Do not edit: the grader replaces this file with its own copy."""
from collections.abc import AsyncIterator
from typing import Protocol


class ProviderError(Exception):
    """The model provider failed (overloaded, network error, bad response)."""


class LLMProvider(Protocol):
    name: str
    price_in_per_mtok: float   # USD per million input tokens
    price_out_per_mtok: float  # USD per million output tokens

    def count_tokens(self, text: str) -> int: ...

    def stream(self, prompt: str, max_output_tokens: int) -> AsyncIterator[str]: ...


def build_prompt(clause_text: str, language: str) -> str:
    lang = "Arabic" if language == "ar" else "English"
    return (f"Explain this contract clause for a junior lawyer in {lang}. "
            f"Quote the words you rely on.\n\n<clause>\n{clause_text}\n</clause>")
