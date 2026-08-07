import logging

import pytest
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
    LoggingConfig,
    SessionConfig,
)
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


@pytest.fixture(scope="module")
def logger_name() -> str:
    return "parameter-resolution-test"


def _make_secret_config() -> AppConfig:
    return AppConfig.model_construct(
        backends=BackendSettings.model_construct(
            openrouter=BackendConfig.model_construct(api_key=["NOT-A-REAL-API-KEY"])
        )
    )


def _make_default_config() -> AppConfig:
    return AppConfig.model_construct(
        host="localhost",
        port=8080,
        command_prefix="!",
        backends=BackendSettings.model_construct(),
        session=SessionConfig.model_construct(),
        auth=AuthConfig.model_construct(),
        logging=LoggingConfig.model_construct(),
    )


def test_logging_masks_secrets(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    resolution = ParameterResolution()
    config = _make_secret_config()
    resolution.record(
        "backends.openrouter.api_key",
        ["NOT-A-REAL-API-KEY"],
        ParameterSource.ENVIRONMENT,
        origin="OPENROUTER_API_KEY",
    )

    with caplog.at_level(logging.DEBUG, logger=logger_name):
        resolution.log(logging.getLogger(logger_name), config)

    assert "NOT-A-REAL-API-KEY" not in caplog.text
    assert "OPENROUTER_API_KEY" in caplog.text
    assert "backends.openrouter.api_key" in caplog.text


def test_logging_records_defaults(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    resolution = ParameterResolution()
    config = _make_default_config()

    with caplog.at_level(logging.DEBUG, logger=logger_name):
        resolution.log(logging.getLogger(logger_name), config)

    assert "host" in caplog.text
    assert "default" in caplog.text.lower()
