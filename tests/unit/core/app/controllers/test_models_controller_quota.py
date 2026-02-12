from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Response
from src.core.app.controllers.models_controller import list_models
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.services.model_capability_index import ModelCapabilitySnapshot
from src.core.services.quota_status_service import get_quota_status_service


@pytest.mark.asyncio
async def test_list_models_propagates_quota_headers() -> None:
    backend_service = MagicMock(spec=IBackendService)

    mock_backend = MagicMock()
    mock_backend.last_quota_headers = {"x-codex-primary-used-percent": "75.5"}
    backend_service.get_active_backends.return_value = {"openai.1": mock_backend}

    routing_service = MagicMock()
    routing_service.get_model_capability_snapshot.return_value = (
        ModelCapabilitySnapshot(
            generation=2,
            model_to_instances={"openai/gpt-4": ("openai.1",)},
            instance_to_models={"openai.1": ("openai/gpt-4",)},
            alias_to_canonical={"openai/gpt-4": "openai/gpt-4"},
            created_at_monotonic=1.0,
        )
    )

    quota_service = get_quota_status_service()
    quota_service.update_quota("openai", {"x-codex-secondary-used-percent": "10.0"})

    response = Response()
    result = await list_models(
        backend_service=backend_service,
        routing_service=routing_service,
        response=response,
    )

    assert result.data[0].id == "openai/gpt-4"
    assert response.headers["x-codex-primary-used-percent"] == "75.5"
    assert response.headers["x-codex-secondary-used-percent"] == "10.0"
