from unittest.mock import patch

from src.core.config.app_config import AppConfig


def test_alibaba_token_plan_key_registers_backend_from_environment() -> None:
    with patch(
        "src.core.config.env.from_env_part3.get_env_value_with_windows_persistent_fallback",
        side_effect=lambda name, **kwargs: (
            ("val-token-plan", "process")
            if name == "ALIBABA_TOKEN_PLAN_API_KEY"
            else (None, "missing")
        ),
    ):
        config = AppConfig.from_env(
            environ={"ALIBABA_TOKEN_PLAN_API_KEY": "val-token-plan"}
        )

    backend = config.backends.lookup("alibaba-token-plan-intl")
    assert backend is not None
    assert backend.api_key == "val-token-plan"


def test_alibaba_token_plan_registers_from_resolved_environment_fallback() -> None:
    with patch(
        "src.core.config.env.from_env_part3.get_env_value_with_windows_persistent_fallback",
        side_effect=lambda name, **kwargs: (
            ("persistent-token-plan", "windows-user")
            if name == "ALIBABA_TOKEN_PLAN_API_KEY"
            else (None, "missing")
        ),
    ):
        config = AppConfig.from_env(environ={})

    backend = config.backends.lookup("alibaba-token-plan-intl")
    assert backend is not None
    assert backend.api_key == "persistent-token-plan"
