"""Unit tests for Cursor CLI dual-auth helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import src.connectors.cursor_cli_auth as cursor_cli_auth
from src.connectors.cursor_cli_auth import (
    CursorAuthPolicy,
    build_cursor_cli_env,
    discovery_modes_to_try,
    env_has_cursor_api_credentials,
    is_cursor_api_key_invalid_error,
    is_cursor_auth_required_error,
    parse_cursor_status_json,
    probe_cursor_cli_auth,
    read_cursor_login_store_api_key,
    resolve_cursor_auth_policy,
)


class TestCursorCliAuthHelpers:
    def test_build_env_strips_credentials_for_cookie_mode(self) -> None:
        env = build_cursor_cli_env(
            "cookie_only",
            base={"CURSOR_API_KEY": "k", "CURSOR_AUTH_TOKEN": "t", "HOME": "h"},
        )
        assert env == {"HOME": "h"}

    def test_build_env_injects_login_store_key_when_env_lacks_credentials(
        self, tmp_path: Path
    ) -> None:
        auth_path = tmp_path / "Cursor" / "auth.json"
        auth_path.parent.mkdir(parents=True)
        auth_path.write_text(
            json.dumps(
                {
                    "accessToken": "access",
                    "refreshToken": "refresh",
                    "apiKey": "crsr_from_login_store",
                }
            ),
            encoding="utf-8",
        )
        with patch(
            "src.connectors.cursor_cli_auth.cursor_auth_json_paths",
            return_value=(auth_path,),
        ):
            env = build_cursor_cli_env("with_env_key", base={"HOME": "h"})
        assert env["CURSOR_API_KEY"] == "crsr_from_login_store"
        assert env["HOME"] == "h"

    def test_build_env_prefers_existing_env_key_over_login_store(
        self, tmp_path: Path
    ) -> None:
        auth_path = tmp_path / "auth.json"
        auth_path.write_text(json.dumps({"apiKey": "crsr_store"}), encoding="utf-8")
        with patch(
            "src.connectors.cursor_cli_auth.cursor_auth_json_paths",
            return_value=(auth_path,),
        ):
            env = build_cursor_cli_env(
                "with_env_key",
                base={"CURSOR_API_KEY": "crsr_env"},
            )
        assert env["CURSOR_API_KEY"] == "crsr_env"

    def test_build_env_uses_explicit_discovery_api_key(self) -> None:
        env = build_cursor_cli_env(
            "with_env_key",
            base={"HOME": "h"},
            discovery_api_key="crsr_cached",
            inject_login_store_key=False,
        )
        assert env["CURSOR_API_KEY"] == "crsr_cached"

    def test_read_cursor_login_store_api_key(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "auth.json"
        auth_path.write_text(
            json.dumps({"apiKey": " crsr_store_key "}), encoding="utf-8"
        )
        with patch(
            "src.connectors.cursor_cli_auth.cursor_auth_json_paths",
            return_value=(auth_path,),
        ):
            assert read_cursor_login_store_api_key() == "crsr_store_key"

    def test_build_env_reuses_cached_login_store_key_when_file_disappears(
        self, tmp_path: Path
    ) -> None:
        auth_path = tmp_path / "Cursor" / "auth.json"
        auth_path.parent.mkdir(parents=True)
        auth_path.write_text(json.dumps({"apiKey": "crsr_cached"}), encoding="utf-8")
        with (
            patch.object(cursor_cli_auth, "_CACHED_LOGIN_STORE_API_KEY", None),
            patch(
                "src.connectors.cursor_cli_auth.cursor_auth_json_paths",
                return_value=(auth_path,),
            ),
        ):
            assert read_cursor_login_store_api_key() == "crsr_cached"
            auth_path.unlink()
            env = build_cursor_cli_env("with_env_key", base={"HOME": "h"})

        assert env["CURSOR_API_KEY"] == "crsr_cached"
        assert env["HOME"] == "h"

    def test_env_has_cursor_api_credentials(self) -> None:
        assert env_has_cursor_api_credentials({"CURSOR_API_KEY": "x"})
        assert env_has_cursor_api_credentials({"CURSOR_AUTH_TOKEN": "x"})
        assert not env_has_cursor_api_credentials({"PATH": "/bin"})

    def test_stderr_classifiers(self) -> None:
        assert is_cursor_auth_required_error(
            "Error: Authentication required. Run 'agent login'"
        )
        assert is_cursor_api_key_invalid_error(
            "Warning: The provided API key is invalid."
        )
        assert not is_cursor_api_key_invalid_error("ok")

    def test_parse_cursor_status_json(self) -> None:
        payload = parse_cursor_status_json(
            '{"isAuthenticated": true, "hasAccessToken": true, "status": "authenticated"}'
        )
        assert payload["isAuthenticated"] is True
        assert parse_cursor_status_json("not-json") == {}

    def test_probe_cursor_cli_auth_parses_status(self) -> None:
        completed = MagicMock(
            returncode=0,
            stdout=(
                '{"status":"authenticated","isAuthenticated":true,'
                '"hasAccessToken":true,"hasRefreshToken":true}'
            ),
            stderr="",
        )
        with patch(
            "src.connectors.cursor_cli_auth.subprocess.run", return_value=completed
        ) as run:
            probe = probe_cursor_cli_auth("agent", mode="cookie_only")

        assert probe.is_authenticated is True
        assert probe.has_access_token is True
        assert "CURSOR_API_KEY" not in run.call_args.kwargs["env"]

    def test_resolve_policy_prefers_cookie_for_acp_when_both_present(self) -> None:
        with (
            patch(
                "src.connectors.cursor_cli_auth.probe_cursor_cli_auth",
                return_value=MagicMock(
                    is_authenticated=True,
                    has_access_token=True,
                ),
            ),
            patch(
                "src.connectors.cursor_cli_auth.env_has_cursor_api_credentials",
                return_value=True,
            ),
            patch(
                "src.connectors.cursor_cli_auth.read_cursor_login_store_api_key",
                return_value="crsr_store",
            ),
        ):
            policy = resolve_cursor_auth_policy("agent")

        assert policy.cookie_usable is True
        assert policy.acp_mode == "cookie_only"
        assert policy.discovery_mode == "cookie_only"
        assert policy.login_store_key_present is True
        assert policy.discovery_key_available is True

    def test_resolve_policy_uses_key_when_cookie_missing(self) -> None:
        with (
            patch(
                "src.connectors.cursor_cli_auth.probe_cursor_cli_auth",
                return_value=MagicMock(
                    is_authenticated=False,
                    has_access_token=False,
                ),
            ),
            patch(
                "src.connectors.cursor_cli_auth.env_has_cursor_api_credentials",
                return_value=True,
            ),
            patch(
                "src.connectors.cursor_cli_auth.read_cursor_login_store_api_key",
                return_value=None,
            ),
        ):
            policy = resolve_cursor_auth_policy("agent")

        assert policy.cookie_usable is False
        assert policy.acp_mode == "with_env_key"
        assert policy.discovery_mode == "with_env_key"

    def test_resolve_policy_uses_login_store_key_when_env_key_absent(self) -> None:
        with (
            patch(
                "src.connectors.cursor_cli_auth.probe_cursor_cli_auth",
                return_value=MagicMock(
                    is_authenticated=True,
                    has_access_token=True,
                ),
            ),
            patch(
                "src.connectors.cursor_cli_auth.env_has_cursor_api_credentials",
                return_value=False,
            ),
            patch(
                "src.connectors.cursor_cli_auth.read_cursor_login_store_api_key",
                return_value="crsr_store",
            ),
        ):
            policy = resolve_cursor_auth_policy("agent")

        assert policy.cookie_usable is True
        assert policy.env_key_present is False
        assert policy.login_store_key_present is True
        assert discovery_modes_to_try(policy) == ["cookie_only", "with_env_key"]

    def test_discovery_modes_cookie_first_then_key(self) -> None:
        policy = CursorAuthPolicy(
            cookie_usable=True,
            env_key_present=True,
            env_key_invalid=False,
            discovery_mode="cookie_only",
            acp_mode="cookie_only",
        )
        assert discovery_modes_to_try(policy) == ["cookie_only", "with_env_key"]

    def test_discovery_modes_include_login_store_key(self) -> None:
        policy = CursorAuthPolicy(
            cookie_usable=True,
            env_key_present=False,
            env_key_invalid=False,
            discovery_mode="cookie_only",
            acp_mode="cookie_only",
            login_store_key_present=True,
        )
        assert discovery_modes_to_try(policy) == ["cookie_only", "with_env_key"]

    def test_discovery_modes_skip_invalid_key(self) -> None:
        policy = CursorAuthPolicy(
            cookie_usable=True,
            env_key_present=True,
            env_key_invalid=True,
            discovery_mode="cookie_only",
            acp_mode="cookie_only",
            login_store_key_present=True,
        )
        assert discovery_modes_to_try(policy) == ["cookie_only"]
