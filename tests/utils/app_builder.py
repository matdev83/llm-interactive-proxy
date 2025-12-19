from src.core.app.application_builder import build_app
from src.core.config.app_config import AppConfig


class AppBuilder:
    def __init__(self) -> None:
        self._dangerous_command_prevention_enabled = True

    def with_dangerous_command_prevention(self, enabled: bool) -> "AppBuilder":
        self._dangerous_command_prevention_enabled = enabled
        return self

    def build(self) -> AppConfig:
        app_config = AppConfig.from_env()
        app_config.session.dangerous_command_prevention_enabled = (
            self._dangerous_command_prevention_enabled
        )
        app_config.app = build_app(app_config)
        return app_config
