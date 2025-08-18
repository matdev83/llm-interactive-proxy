from __future__ import annotations

from enum import Enum


class BackendType(str, Enum):
    """Enum for supported backend types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    GEMINI = "gemini"
    QWEN = "qwen"
    QWEN_OAUTH = "qwen-oauth"
    ZAI = "zai"
