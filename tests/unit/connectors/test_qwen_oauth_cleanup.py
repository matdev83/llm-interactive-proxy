"""Unit tests for Qwen OAuth connector cleanup behavior."""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig


@pytest.fixture
def connector() -> QwenOAuthConnector:
    """Create a QwenOAuthConnector instance for testing cleanup logic."""

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    return QwenOAuthConnector(mock_client, config=AppConfig())


def test_cleanup_stops_file_watching_and_terminates_process(
    connector: QwenOAuthConnector,
) -> None:
    """Connector cleanup should stop file watching and terminate CLI refresh process."""

    mock_process = Mock()
    mock_process.poll.return_value = None
    connector._cli_refresh_process = mock_process

    with patch.object(connector, "_stop_file_watching") as mock_stop:
        connector.__del__()
        mock_stop.assert_called_once()

    mock_process.terminate.assert_called_once()
    assert mock_process.wait.call_count >= 1
    assert connector._cli_refresh_process is None


def test_cleanup_kills_hung_cli_refresh_process(
    connector: QwenOAuthConnector,
) -> None:
    """Connector cleanup should kill CLI process if terminate does not finish it."""

    mock_process = Mock()
    mock_process.poll.return_value = None
    mock_process.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="qwen", timeout=5),
        None,
    ]
    connector._cli_refresh_process = mock_process

    connector.__del__()

    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()
    assert mock_process.wait.call_count == 2
    assert connector._cli_refresh_process is None


def test_cleanup_ignores_errors_during_shutdown(
    connector: QwenOAuthConnector,
) -> None:
    """Exceptions while stopping watchers or processes should be suppressed."""

    connector._cli_refresh_process = Mock()
    connector._cli_refresh_process.poll.side_effect = RuntimeError("boom")

    with patch.object(
        connector, "_stop_file_watching", side_effect=Exception("watch error")
    ):
        connector.__del__()

    # Process attribute should be cleared even when errors occur
    assert connector._cli_refresh_process is None
