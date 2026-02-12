from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from src.core.app.controllers.models_controller import (
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
    get_backend_routing_service,
)


def test_get_backend_routing_service_returns_registered_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.services.backend_routing_service import BackendRoutingService

    expected_service = object()
    provider = MagicMock()
    provider.get_service.return_value = expected_service

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: provider,
    )

    resolved = get_backend_routing_service()

    assert resolved is expected_service
    provider.get_service.assert_called_once_with(BackendRoutingService)


def test_get_backend_routing_service_raises_503_when_not_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    provider.get_service.return_value = None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: provider,
    )

    with pytest.raises(HTTPException) as exc_info:
        get_backend_routing_service()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == HTTP_503_SERVICE_UNAVAILABLE_MESSAGE


def test_get_backend_routing_service_raises_503_when_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: (_ for _ in ()).throw(KeyError("missing provider")),
    )

    with pytest.raises(HTTPException) as exc_info:
        get_backend_routing_service()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
