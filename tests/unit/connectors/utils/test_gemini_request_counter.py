import json
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time
from src.connectors.utils.gemini_request_counter import DailyRequestCounter


@pytest.fixture
def persistence_path(tmp_path: Path) -> Path:
    return tmp_path / "request_count.json"


@pytest.fixture
def logger_mock() -> Generator[MagicMock, None, None]:
    with patch("src.connectors.utils.gemini_request_counter.logger") as mock:
        yield mock


def test_initialization_no_persistence_file(
    persistence_path: Path,
) -> None:
    counter = DailyRequestCounter(persistence_path, limit=100)
    assert counter.count == 0
    assert counter.limit == 100
    assert not persistence_path.exists()


def test_initialization_with_persistence_file(
    persistence_path: Path,
) -> None:
    data = {
        "count": 50,
        "last_reset_date": "2023-01-01",
        "logged_thresholds": [700],
    }
    with open(persistence_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    with patch(
        "src.connectors.utils.gemini_request_counter.DailyRequestCounter._get_current_pacific_date",
        return_value="2023-01-01",
    ):
        counter = DailyRequestCounter(persistence_path, limit=1000)
    assert counter.count == 50
    assert counter.last_reset_date == "2023-01-01"
    assert counter.logged_thresholds == {700}


def test_increment(persistence_path: Path) -> None:
    counter = DailyRequestCounter(persistence_path, limit=100)
    counter.increment()
    assert counter.count == 1

    with open(persistence_path, encoding="utf-8") as f:
        data = json.load(f)
        assert data["count"] == 1


@freeze_time("2023-01-01 10:00:00")
def test_daily_reset(persistence_path: Path) -> None:
    # Initial state
    data = {"count": 50, "last_reset_date": "2022-12-31"}
    with open(persistence_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    counter = DailyRequestCounter(persistence_path, limit=100)
    assert counter.count == 0
    assert counter.logged_thresholds == set()

    # Increment should proceed after reset
    counter.increment()
    assert counter.count == 1
    assert counter.last_reset_date == "2023-01-01"

    with open(persistence_path, encoding="utf-8") as f:
        saved_data = json.load(f)
        assert saved_data["count"] == 1
        assert saved_data["last_reset_date"] == "2023-01-01"


def test_threshold_warnings(persistence_path: Path, logger_mock: MagicMock) -> None:
    counter = DailyRequestCounter(persistence_path, limit=1000)

    # Below first threshold
    for _ in range(699):
        counter.increment()
    logger_mock.warning.assert_not_called()

    # Hit 700 threshold
    counter.increment()
    assert counter.count == 700
    logger_mock.warning.assert_called_once_with(
        "Gemini CLI OAuth personal daily usage reached 700 requests (700/1000)."
    )

    # Cross several more requests but stay below 800
    logger_mock.reset_mock()
    for _ in range(50):
        counter.increment()
    logger_mock.warning.assert_not_called()

    # Hit 800 threshold
    for _ in range(50):
        counter.increment()
    assert counter.count == 800
    logger_mock.warning.assert_called_once_with(
        "Gemini CLI OAuth personal daily usage reached 800 requests (800/1000)."
    )

    # Hit 900 threshold
    logger_mock.reset_mock()
    for _ in range(100):
        counter.increment()
    assert counter.count == 900
    logger_mock.warning.assert_called_once_with(
        "Gemini CLI OAuth personal daily usage reached 900 requests (900/1000)."
    )


def test_no_warning_below_thresholds(
    persistence_path: Path, logger_mock: MagicMock
) -> None:
    counter = DailyRequestCounter(persistence_path, limit=1000)
    for _ in range(699):
        counter.increment()
    logger_mock.warning.assert_not_called()


def test_pacific_time_date_change(persistence_path: Path) -> None:
    # 11 PM Pacific on 2023-01-01
    with freeze_time("2023-01-02 07:00:00", tz_offset=timedelta(hours=0)):
        counter = DailyRequestCounter(persistence_path, limit=100)
        counter.increment()
        assert counter.last_reset_date == "2023-01-01"

    # 1 AM Pacific on 2023-01-02
    with freeze_time("2023-01-02 09:00:00", tz_offset=timedelta(hours=0)):
        counter.increment()
        assert counter.count == 1  # Resets
        assert counter.last_reset_date == "2023-01-02"


def test_thresholds_persist_across_restarts(
    persistence_path: Path, logger_mock: MagicMock
) -> None:
    counter = DailyRequestCounter(persistence_path, limit=1000)

    for _ in range(800):
        counter.increment()

    assert counter.count == 800
    assert counter.logged_thresholds == {700, 800}

    persisted = json.loads(persistence_path.read_text(encoding="utf-8"))
    assert set(persisted["logged_thresholds"]) == {700, 800}

    logger_mock.reset_mock()

    # Simulate restart by creating a new counter instance
    counter_restarted = DailyRequestCounter(persistence_path, limit=1000)
    assert counter_restarted.count == 800
    assert counter_restarted.logged_thresholds == {700, 800}

    for _ in range(100):
        counter_restarted.increment()

    assert counter_restarted.count == 900
    logger_mock.warning.assert_called_once_with(
        "Gemini CLI OAuth personal daily usage reached 900 requests (900/1000)."
    )


def test_reset_clears_logged_thresholds(
    persistence_path: Path,
) -> None:
    counter = DailyRequestCounter(persistence_path, limit=1000)

    for _ in range(700):
        counter.increment()

    assert counter.logged_thresholds == {700}

    # Force next day in Pacific timezone
    future_date = datetime.now() + timedelta(days=1)
    with patch(
        "src.connectors.utils.gemini_request_counter.DailyRequestCounter._get_current_pacific_date",
        return_value=future_date.strftime("%Y-%m-%d"),
    ):
        counter.increment()

    assert counter.count == 1
    assert counter.logged_thresholds == set()
