from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from src.core.database.repositories.usage_repository_types import (
    RepositoryAggregatedStats,
)
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.usage_tracking_service import UsageTrackingService


@pytest.fixture
def mock_usage_repo():
    repo = AsyncMock()
    repo.batch_insert = AsyncMock()
    repo.batch_update = AsyncMock()
    repo.get_by_id_domain = AsyncMock()
    repo.get_aggregated_stats = AsyncMock(return_value=RepositoryAggregatedStats())
    repo.get_status_code_breakdown = AsyncMock(return_value={})
    repo.query_with_filter = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_session_repo():
    return AsyncMock()


@pytest.fixture
def service(mock_usage_repo, mock_session_repo):
    return UsageTrackingService(mock_usage_repo, mock_session_repo)


@pytest.mark.asyncio
async def test_record_request(service, mock_usage_repo):
    record_id = await service.record_request(
        session_id="session-123",
        backend_type="openai",
        model="gpt-4",
        frontend_type="openai",
        leg=TrafficLeg.CLIENT_TO_PROXY,
        prompt_tokens=100,
    )

    assert record_id
    mock_usage_repo.batch_insert.assert_called_once()
    args = mock_usage_repo.batch_insert.call_args[0][0]
    assert len(args) == 1
    assert isinstance(args[0], UsageRecord)
    assert args[0].session_id == "session-123"
    assert args[0].verbatim_prompt_tokens == 100
    assert args[0].mutated_prompt_tokens == 0  # For CTP


@pytest.mark.asyncio
async def test_record_request_ptb(service, mock_usage_repo):
    record_id = await service.record_request(
        session_id="session-123",
        backend_type="openai",
        model="gpt-4",
        frontend_type="openai",
        leg=TrafficLeg.PROXY_TO_BACKEND,
        prompt_tokens=100,
    )

    assert record_id
    args = mock_usage_repo.batch_insert.call_args[0][0]
    assert args[0].mutated_prompt_tokens == 100  # For PTB
    assert args[0].verbatim_prompt_tokens == 0


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_record_response(service, mock_usage_repo):
    mock_record = UsageRecord(
        id="rec-1",
        timestamp=datetime.now(timezone.utc),
        session_id="s1",
        turn_number=1,
        backend_type="openai",
        model="gpt-4",
        frontend_type="openai",
        leg=TrafficLeg.CLIENT_TO_PROXY,
        verbatim_prompt_tokens=100,
        mutated_prompt_tokens=0,
        verbatim_completion_tokens=0,
        mutated_completion_tokens=0,
        total_tokens=100,
    )
    mock_usage_repo.get_by_id_domain.return_value = mock_record

    await service.record_response(
        record_id="rec-1",
        completion_tokens=50,
        backend_reported_usage={"prompt_tokens": 100, "completion_tokens": 50},
    )

    mock_usage_repo.batch_update.assert_called_once()
    updated = mock_usage_repo.batch_update.call_args[0][0][0]
    assert updated.mutated_completion_tokens == 50  # PTC response on CTP record
    assert updated.total_tokens == 150
    assert updated.backend_reported_usage.prompt_tokens == 100


@pytest.mark.asyncio
async def test_get_usage_stats(service, mock_usage_repo):
    mock_usage_repo.get_aggregated_stats.return_value = RepositoryAggregatedStats(
        request_count=10,
        total_tokens=1000,
    )

    filters = StatisticsFilter()
    stats = await service.get_usage_stats(filters)

    assert stats.request_count == 10
    assert stats.total_tokens == 1000
    mock_usage_repo.get_aggregated_stats.assert_called_once_with(filters)
