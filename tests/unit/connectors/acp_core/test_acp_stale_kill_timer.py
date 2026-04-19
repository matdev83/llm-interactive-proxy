"""Tests for ACP stale-process kill timer (BaseAcpConnector)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.acp_core.base_connector import (
    STALE_ACP_AGENT_KILL_DELAY_SECONDS,
)
from src.connectors.acp_core.types import ACPProcessRuntime
from tests.unit.connectors.acp_core.test_base_connector import DummyAcpConnector


@pytest.fixture
def connector() -> DummyAcpConnector:
    cfg = MagicMock()
    cfg.disable_stale_acp_agent_kills = False
    cfg.failure_handling = MagicMock()
    cfg.failure_handling.keepalive_interval = None
    return DummyAcpConnector(cfg, MagicMock())


@pytest.fixture
def runtime(connector: DummyAcpConnector) -> ACPProcessRuntime:
    return connector._create_runtime(Path("/tmp/ws"), "m", "sid")


def test_stale_kill_delay_constant_is_one_hour() -> None:
    assert STALE_ACP_AGENT_KILL_DELAY_SECONDS == 3600.0


@pytest.mark.asyncio
async def test_cancel_stale_kill_timer_cancels_pending_task(
    connector: DummyAcpConnector,
    runtime: ACPProcessRuntime,
) -> None:
    async def _slow() -> None:
        await asyncio.sleep(100.0)

    runtime.stale_kill_task = asyncio.create_task(_slow())
    await connector._cancel_stale_kill_timer(runtime)
    assert runtime.stale_kill_task is None or runtime.stale_kill_task.cancelled()


@pytest.mark.asyncio
async def test_schedule_stale_kill_after_turn_creates_task_when_enabled(
    connector: DummyAcpConnector,
    runtime: ACPProcessRuntime,
) -> None:
    with patch.object(
        connector,
        "_stale_acp_kill_delay_seconds",
        return_value=0.01,
    ):
        await connector._schedule_stale_kill_after_turn(runtime)
    assert runtime.stale_kill_task is not None
    await connector._cancel_stale_kill_timer(runtime)


@pytest.mark.asyncio
async def test_schedule_skipped_when_disable_stale_acp_agent_kills(
    connector: DummyAcpConnector,
    runtime: ACPProcessRuntime,
) -> None:
    connector.config.disable_stale_acp_agent_kills = True
    await connector._schedule_stale_kill_after_turn(runtime)
    assert runtime.stale_kill_task is None


@pytest.mark.asyncio
async def test_stale_kill_task_calls_kill_runtime_after_delay(
    connector: DummyAcpConnector,
    runtime: ACPProcessRuntime,
) -> None:
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 4242
    runtime.process = mock_proc
    with (
        patch.object(
            connector,
            "_stale_acp_kill_delay_seconds",
            return_value=0.01,
        ),
        patch.object(
            connector,
            "_kill_runtime",
            new_callable=AsyncMock,
        ) as mock_kill,
    ):
        await connector._schedule_stale_kill_after_turn(runtime)
        assert runtime.stale_kill_task is not None
        await asyncio.wait_for(runtime.stale_kill_task, timeout=2.0)
    mock_kill.assert_awaited_once_with(runtime)


@pytest.mark.asyncio
async def test_kill_runtime_cancels_stale_kill_task(
    connector: DummyAcpConnector,
    runtime: ACPProcessRuntime,
) -> None:
    async def _slow() -> None:
        await asyncio.sleep(100.0)

    runtime.stale_kill_task = asyncio.create_task(_slow())
    runtime.process = None
    await connector._kill_runtime(runtime)
    assert runtime.stale_kill_task is None or runtime.stale_kill_task.cancelled()
