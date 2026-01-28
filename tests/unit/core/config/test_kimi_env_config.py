from src.core.config.app_config import AppConfig


def test_kimi_api_key_applies_to_kimi_code_backend() -> None:
    config = AppConfig.from_env(environ={"KIMI_API_KEY": "val-kimi"})

    kimi_cfg = config.backends.lookup("kimi-code")
    assert kimi_cfg is not None
    assert kimi_cfg.api_key == "val-kimi"


def test_kimi_api_base_url_override() -> None:
    config = AppConfig.from_env(
        environ={
            "KIMI_API_KEY": "val-kimi",
            "KIMI_API_BASE_URL": "https://example.invalid/kimi/v1",
        }
    )
    kimi_cfg = config.backends.lookup("kimi-code")
    assert kimi_cfg is not None
    assert kimi_cfg.api_url == "https://example.invalid/kimi/v1"
