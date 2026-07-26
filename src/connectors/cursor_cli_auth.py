"""Cursor CLI dual-auth helpers: login cookie vs CURSOR_API_KEY.

Policy (when both are present):
- Prefer local ``agent login`` cookie for ACP/session identity.
- Use ``CURSOR_API_KEY`` / ``CURSOR_AUTH_TOKEN`` for discovery when
  cookie-authenticated ``--list-models`` fails.
- When the process env has no key, reuse ``apiKey`` from Cursor's local
  login store (``auth.json``) for discovery only — some CLI builds reject
  cookie-only ``--list-models`` even while ``agent status`` is authenticated.
- Never keep a rejected/invalid env key in child env when cookie auth works.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

CURSOR_AUTH_ENV_KEYS: tuple[str, ...] = ("CURSOR_API_KEY", "CURSOR_AUTH_TOKEN")
_CACHED_LOGIN_STORE_API_KEY: str | None = None

CursorAuthMode = Literal["cookie_only", "with_env_key"]


@dataclass(frozen=True)
class CursorAuthProbe:
    """Result of ``agent status --format json`` under a controlled env."""

    mode: CursorAuthMode
    is_authenticated: bool
    has_access_token: bool
    has_refresh_token: bool
    raw_status: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class CursorAuthPolicy:
    """Resolved auth modes for discovery and ACP child processes."""

    cookie_usable: bool
    env_key_present: bool
    env_key_invalid: bool
    discovery_mode: CursorAuthMode
    acp_mode: CursorAuthMode
    login_store_key_present: bool = False

    @property
    def discovery_key_available(self) -> bool:
        """True when discovery can use an env key or login-store apiKey."""
        if self.env_key_invalid:
            return False
        return self.env_key_present or self.login_store_key_present

    @property
    def any_usable(self) -> bool:
        if self.cookie_usable:
            return True
        return self.discovery_key_available


def cursor_auth_json_paths() -> tuple[Path, ...]:
    """Candidate paths for Cursor CLI ``auth.json`` (login store)."""

    home = Path.home()
    appdata = os.environ.get("APPDATA", "").strip()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    candidates: list[Path] = []
    if appdata:
        # Windows Cursor CLI uses %APPDATA%\\Cursor\\auth.json
        candidates.append(Path(appdata) / "Cursor" / "auth.json")
        candidates.append(Path(appdata) / "cursor" / "auth.json")
    candidates.append(home / ".cursor" / "auth.json")
    if xdg:
        candidates.append(Path(xdg) / "cursor" / "auth.json")
    candidates.append(home / ".config" / "cursor" / "auth.json")
    # Deduplicate while preserving order
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
    return tuple(ordered)


def read_cursor_login_store_api_key() -> str | None:
    """Read ``apiKey`` from Cursor's local login store when present.

    The last known good value stays cached in memory so model discovery can
    keep working if Cursor unlinks ``auth.json`` after startup.
    """

    global _CACHED_LOGIN_STORE_API_KEY
    for path in cursor_auth_json_paths():
        try:
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            logger.debug(
                "Failed reading Cursor login store at %s",
                path,
                exc_info=True,
            )
            continue
        if not isinstance(payload, dict):
            continue
        api_key = payload.get("apiKey")
        if isinstance(api_key, str):
            stripped_api_key = api_key.strip()
            if stripped_api_key:
                _CACHED_LOGIN_STORE_API_KEY = stripped_api_key
                return stripped_api_key
    return _CACHED_LOGIN_STORE_API_KEY


def build_cursor_cli_env(
    mode: CursorAuthMode,
    *,
    base: Mapping[str, str] | None = None,
    inject_login_store_key: bool = True,
    discovery_api_key: str | None = None,
) -> dict[str, str]:
    """Copy process env and either strip or keep Cursor API key credentials.

    For ``with_env_key``, when the process env has no Cursor credentials,
    inject ``discovery_api_key`` when provided, otherwise read ``apiKey`` from
    the local login store. Callers that already read the store should pass
    ``discovery_api_key`` so a mid-flight delete of ``auth.json`` cannot drop
    the credential between policy probe and ``--list-models``.
    """

    env = dict(base if base is not None else os.environ)
    if mode == "cookie_only":
        for key in CURSOR_AUTH_ENV_KEYS:
            env.pop(key, None)
        return env

    if not env_has_cursor_api_credentials(env):
        api_key_value = discovery_api_key
        if api_key_value is None and inject_login_store_key:
            api_key_value = read_cursor_login_store_api_key()
        if api_key_value:
            env["CURSOR_API_KEY"] = api_key_value
    return env


def env_has_cursor_api_credentials(
    env: Mapping[str, str] | None = None,
) -> bool:
    source = env if env is not None else os.environ
    return any(bool(str(source.get(key) or "").strip()) for key in CURSOR_AUTH_ENV_KEYS)


def is_cursor_auth_required_error(stderr: str) -> bool:
    text = stderr.lower()
    return "authentication required" in text or "not logged in" in text


def is_cursor_api_key_invalid_error(stderr: str) -> bool:
    text = stderr.lower()
    return "api key is invalid" in text or "provided api key is invalid" in text


def parse_cursor_status_json(stdout: str) -> dict[str, object]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def probe_cursor_cli_auth(
    executable: str,
    *,
    mode: CursorAuthMode,
    timeout_seconds: float = 30.0,
    env_base: Mapping[str, str] | None = None,
) -> CursorAuthProbe:
    """Run ``agent status --format json`` under a controlled auth env."""

    # Status probes must not inject login-store keys: that can flip status to
    # unauthenticated even when cookies are valid.
    env = build_cursor_cli_env(mode, base=env_base, inject_login_store_key=False)
    try:
        result = subprocess.run(
            [executable, "status", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            env=env,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        logger.warning(
            "Cursor auth probe failed for mode=%s",
            mode,
            exc_info=True,
        )
        return CursorAuthProbe(
            mode=mode,
            is_authenticated=False,
            has_access_token=False,
            has_refresh_token=False,
        )

    payload = parse_cursor_status_json(result.stdout or "")
    is_authenticated = bool(payload.get("isAuthenticated"))
    # Some CLI builds report status="authenticated" without the bool flag.
    status_value = payload.get("status")
    if not is_authenticated and isinstance(status_value, str):
        is_authenticated = status_value.strip().lower() == "authenticated"
    message = payload.get("message")
    return CursorAuthProbe(
        mode=mode,
        is_authenticated=is_authenticated,
        has_access_token=bool(payload.get("hasAccessToken")),
        has_refresh_token=bool(payload.get("hasRefreshToken")),
        raw_status=str(status_value) if status_value is not None else None,
        message=str(message) if isinstance(message, str) else None,
    )


def resolve_cursor_auth_policy(
    executable: str,
    *,
    timeout_seconds: float = 30.0,
    env_base: Mapping[str, str] | None = None,
    env_key_invalid: bool = False,
) -> CursorAuthPolicy:
    """Probe cookie vs env-key auth and select discovery/ACP modes."""

    env_key_present = env_has_cursor_api_credentials(env_base)
    login_store_key_present = bool(read_cursor_login_store_api_key())
    cookie_probe = probe_cursor_cli_auth(
        executable,
        mode="cookie_only",
        timeout_seconds=timeout_seconds,
        env_base=env_base,
    )
    cookie_usable = cookie_probe.is_authenticated or cookie_probe.has_access_token

    if cookie_usable:
        # Cookie wins for ACP even when a key is also present.
        discovery_mode: CursorAuthMode = "cookie_only"
        acp_mode: CursorAuthMode = "cookie_only"
    elif (env_key_present or login_store_key_present) and not env_key_invalid:
        discovery_mode = "with_env_key"
        acp_mode = "with_env_key"
    else:
        discovery_mode = "cookie_only"
        acp_mode = "cookie_only"

    return CursorAuthPolicy(
        cookie_usable=cookie_usable,
        env_key_present=env_key_present,
        env_key_invalid=env_key_invalid,
        discovery_mode=discovery_mode,
        acp_mode=acp_mode,
        login_store_key_present=login_store_key_present,
    )


def discovery_modes_to_try(policy: CursorAuthPolicy) -> list[CursorAuthMode]:
    """Ordered discovery env modes: cookie-first, then key fallback when useful."""

    modes: list[CursorAuthMode] = ["cookie_only"]
    if policy.discovery_key_available:
        # list-models may require a key even when cookie status is authenticated.
        modes.append("with_env_key")
    return modes
