from src.core.config.app_config import AppConfig


def test_opencode_go_api_key_applies_to_backend() -> None:
    config = AppConfig.from_env(environ={"OPENCODE_GO_API_KEY": "val-opencode-go"})

    opencode_go_cfg = config.backends.lookup("opencode-go")
    assert opencode_go_cfg is not None
    assert opencode_go_cfg.api_key == "val-opencode-go"


def test_opencode_go_api_base_url_override() -> None:
    config = AppConfig.from_env(
        environ={
            "OPENCODE_GO_API_KEY": "val-opencode-go",
            "OPENCODE_GO_API_BASE_URL": "https://example.invalid/opencode-go/v1",
        }
    )

    opencode_go_cfg = config.backends.lookup("opencode-go")
    assert opencode_go_cfg is not None
    assert opencode_go_cfg.api_url == "https://example.invalid/opencode-go/v1"
