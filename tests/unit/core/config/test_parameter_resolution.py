import logging

import pytest
from src.core.config.app_config import AppConfig
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


@pytest.fixture()
def logger_name() -> str:
    return "parameter-resolution-test"


def test_logging_masks_secrets(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    resolution = ParameterResolution()
    config = AppConfig()
    config.backends.openrouter.api_key = ["NOT-A-REAL-API-KEY"]
    resolution.record(
        "backends.openrouter.api_key",
        ["NOT-A-REAL-API-KEY"],
        ParameterSource.ENVIRONMENT,
        origin="OPENROUTER_API_KEY",
    )

    with caplog.at_level(logging.INFO, logger=logger_name):
        resolution.log(logging.getLogger(logger_name), config)

    assert "NOT-A-REAL-API-KEY" not in caplog.text
    assert "OPENROUTER_API_KEY" in caplog.text
    assert "backends.openrouter.api_key" in caplog.text


def test_logging_records_defaults(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    resolution = ParameterResolution()
    config = AppConfig()

    with caplog.at_level(logging.INFO, logger=logger_name):
        resolution.log(logging.getLogger(logger_name), config)

    assert "host" in caplog.text
    assert "default" in caplog.text.lower()
