"""Auth scope resolver implementation for B2BUA continuity scoping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from src.core.domain.request_context import RequestContext
from src.core.interfaces.auth_scope_resolver_interface import IAuthScopeResolver
from src.core.interfaces.configuration_interface import IConfig

_LOCALHOST_SCOPE_ID: Final[str] = "localhost"
_LOCALHOST_HOSTS: Final[set[str]] = {"127.0.0.1", "localhost", "::1"}


class DefaultAuthScopeResolver(IAuthScopeResolver):
    """Resolve auth scope from injected state or localhost implicit scope."""

    def __init__(self, config: IConfig | None = None) -> None:
        self._config = config

    async def resolve_auth_scope_id(self, context: RequestContext) -> str | None:
        """Resolve auth scope identifier for continuity decisions."""
        if scoped_id := self._extract_state_scope_id(context.state):
            return scoped_id

        if self._is_single_user_localhost_mode():
            return _LOCALHOST_SCOPE_ID

        return None

    @staticmethod
    def build_continuity_scope_key(
        auth_scope_id: str | None,
        client_session_id: str | None,
    ) -> tuple[str, str] | None:
        """Build continuity key tuple scoped by auth scope and client session.

        Continuity is only available when both identifiers are present.
        """
        normalized_auth_scope = (
            auth_scope_id.strip()
            if isinstance(auth_scope_id, str) and auth_scope_id.strip()
            else None
        )
        normalized_client_session = (
            client_session_id.strip()
            if isinstance(client_session_id, str) and client_session_id.strip()
            else None
        )

        if normalized_auth_scope is None or normalized_client_session is None:
            return None

        return normalized_auth_scope, normalized_client_session

    @staticmethod
    def _extract_state_scope_id(state: Any) -> str | None:
        if not isinstance(state, Mapping):
            return None

        for key in ("auth_scope_id", "authenticated_token_id", "token_id"):
            candidate = state.get(key)
            if isinstance(candidate, str):
                normalized = candidate.strip()
                if normalized:
                    return normalized
        return None

    def _is_single_user_localhost_mode(self) -> bool:
        if self._config is None:
            return False

        host = getattr(self._config, "host", None)
        if not isinstance(host, str) or host.strip().lower() not in _LOCALHOST_HOSTS:
            return False

        access_mode = getattr(self._config, "access_mode", None)
        if access_mode is None or not hasattr(access_mode, "is_single_user"):
            return False

        try:
            return bool(access_mode.is_single_user())
        except (AttributeError, TypeError):
            return False
