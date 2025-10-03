"""Tests for usage tracking cost extraction logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from src.core.interfaces.repositories_interface import IUsageRepository
from src.core.services.usage_tracking_service import UsageTrackingService


@pytest.fixture
def mock_repository() -> AsyncMock:
    """Create a mock usage repository that returns the entity being added."""

    repo = AsyncMock(spec=IUsageRepository)

    async def _add(entity):
        return entity

    repo.add.side_effect = _add
    return repo


@pytest.mark.asyncio
async def test_track_request_uses_billing_cost(
    mock_repository: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Track request should store billing-derived cost when available."""

    service = UsageTrackingService(mock_repository)

    monkeypatch.setattr(
        "src.core.services.usage_tracking_service.extract_billing_info_from_headers",
        lambda headers, backend: {"usage": {}, "cost": "1.25"},
    )
    monkeypatch.setattr(
        "src.core.services.usage_tracking_service.extract_billing_info_from_response",
        lambda response, backend: {"usage": {}, "cost": "2.5"},
    )

    async with service.track_request(
        model="gpt-4", backend="openai", messages=[]
    ) as tracker:
        tracker.set_response_headers({"x-test": "value"})
        tracker.set_response({"id": "resp"})

    usage_data = mock_repository.add.await_args.args[0]
    assert usage_data.cost == pytest.approx(2.5)
    assert tracker.cost == pytest.approx(2.5)
    assert tracker.usage_data is usage_data


@pytest.mark.asyncio
async def test_track_request_preserves_manual_cost(
    mock_repository: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manual cost overrides billing-derived values."""

    service = UsageTrackingService(mock_repository)

    monkeypatch.setattr(
        "src.core.services.usage_tracking_service.extract_billing_info_from_headers",
        lambda headers, backend: {"usage": {}, "cost": "3.5"},
    )
    monkeypatch.setattr(
        "src.core.services.usage_tracking_service.extract_billing_info_from_response",
        lambda response, backend: {"usage": {}, "cost": "4.0"},
    )

    async with service.track_request(
        model="gpt-4", backend="openai", messages=[]
    ) as tracker:
        tracker.set_cost(9.99)
        tracker.set_response_headers({"x-test": "value"})
        tracker.set_response({"id": "resp"})

    usage_data = mock_repository.add.await_args.args[0]
    assert usage_data.cost == pytest.approx(9.99)
    assert tracker.cost == pytest.approx(9.99)
    assert tracker.usage_data is usage_data
