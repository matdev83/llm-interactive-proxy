from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from src.core.config.app_config import AppConfig
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.command_policy_service_interface import ICommandPolicyService

if TYPE_CHECKING:
    from src.core.domain.session import Session

logger = logging.getLogger(__name__)

_TRUE_STRINGS = {"1", "true", "yes", "on", "enable", "enabled"}
_FALSE_STRINGS = {"0", "false", "no", "off", "disable", "disabled"}


def _coerce_env_flag(value: str | None) -> bool | None:
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None

    if normalized in _TRUE_STRINGS:
        return True
    if normalized in _FALSE_STRINGS:
        return False
    return None


class CommandPolicyService(ICommandPolicyService):
    """Resolves policy decisions for interactive commands."""

    def __init__(
        self,
        config: AppConfig,
        app_state: IApplicationState | None = None,
    ) -> None:
        self._config = config
        self._app_state = app_state

    def is_static_route_enforced(self) -> bool:
        static_route = getattr(self._config.backends, "static_route", None)
        if isinstance(static_route, str) and static_route.strip():
            return True

        env_route = os.environ.get("STATIC_ROUTE")
        return bool(env_route and env_route.strip())

    def are_interactive_commands_disabled(self, session: Session | None = None) -> bool:
        # App-state overrides take precedence because they capture runtime flags.
        if self._app_state is not None:
            try:
                if self._app_state.get_disable_interactive_commands():
                    return True
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug(
                    "Unable to read disable_interactive_commands from app state: %s",
                    exc,
                    exc_info=True,
                )

        env_value = _coerce_env_flag(os.environ.get("DISABLE_INTERACTIVE_COMMANDS"))
        if env_value is True:
            return True
        if env_value is False:
            return False

        # Config defaults apply when no override exists.
        disable_in_config = getattr(
            self._config.session, "disable_interactive_commands", False
        )
        return bool(disable_in_config)

    def should_apply_strict_detection(self) -> bool:
        env_value = _coerce_env_flag(os.environ.get("STRICT_COMMAND_DETECTION"))
        if env_value is not None:
            return env_value

        return bool(getattr(self._config, "strict_command_detection", False))

    def resolve_command_prefix(
        self, session: Session | None, fallback_prefix: str
    ) -> str:
        if session is not None:
            try:
                override = getattr(session.state, "command_prefix_override", None)
            except Exception:  # pragma: no cover - defensive
                override = None
            if isinstance(override, str) and override.strip():
                return override

        if self._app_state is not None:
            try:
                app_prefix = self._app_state.get_command_prefix()
            except Exception as exc:  # pragma: no cover
                logger.debug(
                    "Unable to read command prefix from app state: %s",
                    exc,
                    exc_info=True,
                )
                app_prefix = None
            if isinstance(app_prefix, str) and app_prefix.strip():
                return app_prefix

        config_prefix = getattr(self._config, "command_prefix", None)
        if isinstance(config_prefix, str) and config_prefix.strip():
            return config_prefix

        return fallback_prefix if fallback_prefix else "!/"
