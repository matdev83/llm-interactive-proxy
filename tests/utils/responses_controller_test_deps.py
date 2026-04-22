from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.core.domain.backend_target import BackendTarget
from src.core.interfaces.backend_model_resolver_interface import IBackendModelResolver
from src.core.interfaces.responses_session_store_interface import IResponsesSessionStore
from src.core.services.anthropic_responses_projector import AnthropicResponsesProjector
from src.core.services.gemini_responses_projector import GeminiResponsesProjector
from src.core.services.in_memory_responses_session_store import (
    InMemoryResponsesSessionStore,
)
from src.core.services.openai_responses_projector import OpenAIResponsesProjector


def build_responses_controller_backend_kwargs() -> dict[str, Any]:
    store: IResponsesSessionStore = InMemoryResponsesSessionStore()
    resolver = MagicMock(spec=IBackendModelResolver)

    async def _resolve_target(
        request: object, context: object | None = None
    ) -> BackendTarget:
        model = getattr(request, "model", "gpt-test")
        if isinstance(model, str) and ":" in model:
            backend, rest = model.split(":", 1)
            return BackendTarget(backend=backend, model=rest, uri_params={})
        return BackendTarget(
            backend="openai-responses", model=str(model), uri_params={}
        )

    resolver.resolve_target = AsyncMock(side_effect=_resolve_target)
    return {
        "responses_session_store": store,
        "backend_model_resolver": resolver,
        "openai_responses_projector": OpenAIResponsesProjector(),
        "anthropic_responses_projector": AnthropicResponsesProjector(),
        "gemini_responses_projector": GeminiResponsesProjector(),
    }
