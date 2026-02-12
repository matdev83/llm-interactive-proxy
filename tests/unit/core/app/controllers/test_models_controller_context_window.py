from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.core.app.controllers.models_controller import _list_models_impl
from src.core.domain.models_listing import ModelsListingResponse
from src.core.services.model_capability_index import ModelCapabilitySnapshot


@pytest.mark.asyncio
async def test_list_models_populates_context_window_from_capability_snapshot() -> None:
    backend_service = MagicMock()
    backend_service.get_active_backends.return_value = {}

    routing_service = MagicMock()
    routing_service.get_model_capability_snapshot.return_value = (
        ModelCapabilitySnapshot(
            generation=5,
            model_to_instances={
                "openai/gpt-4": ("openai.1",),
                "google/gemini-1.5-pro": ("google.1",),
            },
            instance_to_models={
                "openai.1": ("openai/gpt-4",),
                "google.1": ("google/gemini-1.5-pro",),
            },
            alias_to_canonical={
                "openai/gpt-4": "openai/gpt-4",
                "google/gemini-1.5-pro": "google/gemini-1.5-pro",
            },
            created_at_monotonic=1.0,
        )
    )

    response, _ = await _list_models_impl(
        backend_service=backend_service,
        routing_service=routing_service,
    )

    assert isinstance(response, ModelsListingResponse)
    model_ids = [m.id for m in response.data]
    assert "openai/gpt-4" in model_ids
    assert "google/gemini-1.5-pro" in model_ids

    gpt4 = next(m for m in response.data if m.id == "openai/gpt-4")
    assert gpt4.context_window is not None

    gemini = next(m for m in response.data if m.id == "google/gemini-1.5-pro")
    assert gemini.context_window is None or gemini.context_window > 0


@pytest.mark.asyncio
async def test_list_models_returns_empty_list_for_empty_snapshot() -> None:
    backend_service = MagicMock()
    backend_service.get_active_backends.return_value = {}

    routing_service = MagicMock()
    routing_service.get_model_capability_snapshot.return_value = (
        ModelCapabilitySnapshot(
            generation=6,
            model_to_instances={},
            instance_to_models={},
            alias_to_canonical={},
            created_at_monotonic=2.0,
        )
    )

    response, _ = await _list_models_impl(
        backend_service=backend_service,
        routing_service=routing_service,
    )

    assert response.data == []
