from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response
from src.core.app.controllers.models_controller import list_models
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.services.model_capability_index import ModelCapabilitySnapshot


def _snapshot() -> ModelCapabilitySnapshot:
    return ModelCapabilitySnapshot(
        generation=3,
        model_to_instances={
            "openai/gpt-4o": ("openai.1", "openai.2"),
            "anthropic/claude-3-5-sonnet": ("anthropic.1",),
        },
        instance_to_models={
            "openai.1": ("openai/gpt-4o",),
            "openai.2": ("openai/gpt-4o",),
            "anthropic.1": ("anthropic/claude-3-5-sonnet",),
        },
        alias_to_canonical={
            "gpt-4o": "openai/gpt-4o",
            "openai/gpt-4o": "openai/gpt-4o",
            "claude-3-5-sonnet": "anthropic/claude-3-5-sonnet",
            "anthropic/claude-3-5-sonnet": "anthropic/claude-3-5-sonnet",
        },
        created_at_monotonic=1.0,
    )


def _empty_snapshot() -> ModelCapabilitySnapshot:
    return ModelCapabilitySnapshot(
        generation=4,
        model_to_instances={},
        instance_to_models={},
        alias_to_canonical={},
        created_at_monotonic=2.0,
    )


@pytest.mark.asyncio
async def test_list_models_returns_canonical_capability_index_output() -> None:
    backend_service = MagicMock(spec=IBackendService)
    backend_service.get_active_backends.return_value = {}

    routing_service = MagicMock()
    routing_service.get_model_capability_snapshot.return_value = _snapshot()

    response = await list_models(
        response=Response(),
        backend_service=backend_service,
        routing_service=routing_service,
    )

    ids = [model.id for model in response.data]
    assert "openai/gpt-4o" in ids
    assert "anthropic/claude-3-5-sonnet" in ids
    assert "openai:gpt-4o" not in ids


@pytest.mark.asyncio
async def test_list_models_returns_empty_when_snapshot_has_no_models() -> None:
    backend_service = MagicMock(spec=IBackendService)
    backend_service.get_active_backends.return_value = {}

    routing_service = MagicMock()
    routing_service.get_model_capability_snapshot.return_value = _empty_snapshot()

    response = await list_models(
        response=Response(),
        backend_service=backend_service,
        routing_service=routing_service,
    )

    assert response.data == []


@pytest.mark.asyncio
async def test_list_models_returns_503_when_routing_service_contract_missing() -> None:
    backend_service = MagicMock(spec=IBackendService)
    backend_service.get_active_backends.return_value = {}

    with pytest.raises(HTTPException) as exc_info:
        await list_models(
            response=Response(),
            backend_service=backend_service,
            routing_service=object(),
        )

    assert exc_info.value.status_code == 503
