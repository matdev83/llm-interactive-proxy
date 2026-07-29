from src.core.config.app_config import AppConfig


def test_alibaba_token_plan_key_registers_backend_from_environment() -> None:
    config = AppConfig.from_env(
        environ={"ALIBABA_TOKEN_PLAN_API_KEY": "val-token-plan"}
    )

    backend = config.backends.lookup("alibaba-token-plan-intl")
    assert backend is not None
    assert backend.api_key == "val-token-plan"
