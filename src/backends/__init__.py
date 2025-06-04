from __future__ import annotations

import os

from .openrouter_backend import OpenRouterBackend
from .registry import register_backend, get_backend, select_backend

# Register default OpenRouter backend
openrouter_backend = OpenRouterBackend(
    api_key=os.getenv("OPENROUTER_API_KEY", ""),
    base_url=os.getenv("OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"),
)
register_backend(openrouter_backend)

__all__ = ["register_backend", "get_backend", "select_backend", "openrouter_backend"]
