from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.services.composite_leaf_target_resolver_adapter import (
    CompositeLeafTargetResolverAdapter,
)


def _request() -> ChatRequest:
    return ChatRequest(
        model="openai:gpt-4|anthropic:claude-3-5-sonnet",
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={"session_id": "session-1"},
    )


def _context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-composite-leaf",
        session_id="session-composite-leaf",
    )


@pytest.mark.asyncio
async def test_leaf_adapter_resolves_leaf_selector_via_backend_model_resolver() -> None:
    backend_model_resolver = MagicMock()
    context = _context()

    async def _resolve_target(
        *, request: ChatRequest, context: RequestContext | None
    ) -> BackendTarget:
        assert context is not None
        assert context.extensions["composite_leaf_resolution"] is True
        return BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": "0.2"},
        )

    backend_model_resolver.resolve_target = AsyncMock(side_effect=_resolve_target)
    adapter = CompositeLeafTargetResolverAdapter(
        backend_model_resolver=backend_model_resolver
    )

    target = await adapter.resolve_leaf(
        request=_request(),
        context=context,
        leaf_selector="openai:gpt-4?temperature=0.2",
    )

    assert target.backend == "openai"
    assert target.model == "gpt-4"
    assert target.uri_params == {"temperature": "0.2"}
    assert context.extensions.get("composite_leaf_resolution") is None

    resolver_request = backend_model_resolver.resolve_target.await_args.kwargs[
        "request"
    ]
    assert resolver_request.extra_body.get("_resolved_uri_params") == {
        "temperature": "0.2",
    }


@pytest.mark.asyncio
async def test_explicit_leaf_purges_inherited_backend_type_from_extra_body() -> None:
    backend_model_resolver = MagicMock()
    context = _context()

    async def _resolve_target(
        *, request: ChatRequest, context: RequestContext | None
    ) -> BackendTarget:
        assert request.extra_body.get("backend_type") is None
        return BackendTarget(
            backend="anthropic",
            model="claude-3-5-sonnet",
            uri_params={},
        )

    backend_model_resolver.resolve_target = AsyncMock(side_effect=_resolve_target)
    adapter = CompositeLeafTargetResolverAdapter(
        backend_model_resolver=backend_model_resolver
    )

    request = _request()
    request = request.model_copy(
        update={"extra_body": {**(request.extra_body or {}), "backend_type": "openai"}}
    )

    await adapter.resolve_leaf(
        request=request,
        context=context,
        leaf_selector="anthropic:claude-3-5-sonnet",
    )


@pytest.mark.asyncio
async def test_leaf_resolved_uri_params_reset_to_leaf_local_not_parent_stale() -> None:
    backend_model_resolver = MagicMock()
    backend_model_resolver.resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={},
        )
    )
    adapter = CompositeLeafTargetResolverAdapter(
        backend_model_resolver=backend_model_resolver
    )
    request = _request()
    request = request.model_copy(
        update={
            "extra_body": {
                **(request.extra_body or {}),
                "_resolved_uri_params": {"stale": "yes", "temperature": "0.9"},
            }
        }
    )

    await adapter.resolve_leaf(
        request=request,
        context=_context(),
        leaf_selector="openai:gpt-4",
    )

    resolver_request = backend_model_resolver.resolve_target.await_args.kwargs[
        "request"
    ]
    assert resolver_request.extra_body.get("_resolved_uri_params") == {}


@pytest.mark.asyncio
async def test_model_only_leaf_preserves_inherited_backend_type_in_extra_body() -> None:
    backend_model_resolver = MagicMock()

    async def _resolve_target(
        *, request: ChatRequest, context: RequestContext | None
    ) -> BackendTarget:
        assert request.extra_body.get("backend_type") == "gemini"
        return BackendTarget(backend="gemini", model="gemini-2.0-flash", uri_params={})

    backend_model_resolver.resolve_target = AsyncMock(side_effect=_resolve_target)
    adapter = CompositeLeafTargetResolverAdapter(
        backend_model_resolver=backend_model_resolver
    )
    request = _request()
    request = request.model_copy(
        update={"extra_body": {**(request.extra_body or {}), "backend_type": "gemini"}}
    )

    await adapter.resolve_leaf(
        request=request,
        context=_context(),
        leaf_selector="gemini-2.0-flash",
    )


@pytest.mark.asyncio
async def test_model_only_leaf_without_query_preserves_inherited_resolved_uri_params() -> (
    None
):
    backend_model_resolver = MagicMock()
    backend_model_resolver.resolve_target = AsyncMock(
        return_value=BackendTarget(backend="openai", model="gpt-4", uri_params={})
    )
    adapter = CompositeLeafTargetResolverAdapter(
        backend_model_resolver=backend_model_resolver
    )
    request = _request()
    request = request.model_copy(
        update={
            "extra_body": {
                **(request.extra_body or {}),
                "_resolved_uri_params": {"temperature": "0.4", "top_p": "0.8"},
            }
        }
    )

    await adapter.resolve_leaf(
        request=request,
        context=_context(),
        leaf_selector="gpt-4",
    )

    resolver_request = backend_model_resolver.resolve_target.await_args.kwargs[
        "request"
    ]
    assert resolver_request.extra_body.get("_resolved_uri_params") == {
        "temperature": "0.4",
        "top_p": "0.8",
    }


@pytest.mark.asyncio
async def test_leaf_adapter_does_not_mutate_original_request_model() -> None:
    backend_model_resolver = MagicMock()
    backend_model_resolver.resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="anthropic",
            model="claude-3-5-sonnet",
            uri_params={},
        )
    )
    adapter = CompositeLeafTargetResolverAdapter(
        backend_model_resolver=backend_model_resolver
    )
    request = _request()
    context = _context()

    await adapter.resolve_leaf(
        request=request,
        context=context,
        leaf_selector="anthropic:claude-3-5-sonnet",
    )

    assert backend_model_resolver.resolve_target.await_args is not None
    resolver_request = backend_model_resolver.resolve_target.await_args.kwargs[
        "request"
    ]
    assert resolver_request.model == "anthropic:claude-3-5-sonnet"
    assert request.model == "openai:gpt-4|anthropic:claude-3-5-sonnet"
