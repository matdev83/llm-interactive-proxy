from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.services.backend_model_resolver import BackendModelResolver


@pytest.mark.asyncio
async def test_non_composite_entrypoint_does_not_publish_composite_diagnostics() -> (
    None
):
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    routing_service = MagicMock()
    routing_service.resolve_model_only_backend.return_value = "openai"
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = "gpt-4o"
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    composite_routing_service = MagicMock()
    composite_routing_service.resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="openai",
            model="gpt-4o",
            uri_params={},
        )
    )

    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
        composite_routing_service=composite_routing_service,
    )
    context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
    context.extensions["composite_routing_surface"] = "main"
    request = ChatRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={},
    )

    result = await resolver.resolve_target(request, context=context)

    assert result.backend == "openai"
    assert result.model == "gpt-4o"
    assert composite_routing_service.resolve_target.await_args is not None
    assert "composite_routing_diagnostics" not in context.extensions
