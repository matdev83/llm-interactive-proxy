"""Interfaces for ProxyMem feature."""

from __future__ import annotations

from typing import Protocol


class LLMCaller(Protocol):
    """Protocol for LLM callers."""

    async def __call__(
        self, prompt: str, *, max_tokens: int | None = None
    ) -> str | None:
        """Call an LLM with a prompt."""
        ...
