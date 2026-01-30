import asyncio
import contextlib
import logging
import re
import secrets
import time
import webbrowser
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from src.connectors.gemini_oauth_auto.constants import (
    ACCOUNT_ID_PATTERN,
    AUTH_URL,
    FAILURE_REDIRECT,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_SCOPES,
    SUCCESS_REDIRECT,
    TOKEN_URL,
    USERINFO_URL,
)
from src.connectors.gemini_oauth_auto.errors import OAuthError
from src.connectors.gemini_oauth_auto.interfaces import ITokenStorage
from src.connectors.gemini_oauth_auto.models import StoredAccount

# Compiled regex for account ID validation
_ACCOUNT_ID_REGEX = re.compile(ACCOUNT_ID_PATTERN)

logger = logging.getLogger(__name__)


class OAuthFlowService:
    """OAuth flow service for browser-based authorization.

    Used by the management script, not the runtime connector.
    """

    def __init__(
        self,
        storage: ITokenStorage,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize OAuth flow service.

        Args:
            storage: Token storage service for persisting new accounts
            http_client: httpx.AsyncClient for HTTP requests
        """
        self._storage = storage
        self._http_client = http_client or httpx.AsyncClient()

    async def authorize(
        self,
        account_id: str | None = None,
        port: int | None = None,
        timeout: int = 120,
        open_browser: bool = True,
    ) -> StoredAccount:
        """Run OAuth authorization flow.

        Args:
            account_id: Custom account identifier (auto-generated if None)
            port: Fixed port for callback server (dynamic if None)
            timeout: Seconds to wait for authorization
            open_browser: Whether to auto-open browser

        Returns:
            StoredAccount with tokens and email

        Raises:
            OAuthError: On failure or timeout
        """
        # 1. Prepare flow parameters
        state = self._generate_state()
        # Use port 0 for random available port if None
        callback_port = port or 0

        # Start server first to get the actual port if it was 0
        app = FastAPI()
        code_received: asyncio.Future[str] = asyncio.Future()

        @app.get("/oauth2callback")
        async def callback(request: Request) -> RedirectResponse:
            return await self._handle_callback_logic(
                received_state=request.query_params.get("state"),
                code=request.query_params.get("code"),
                error=request.query_params.get("error"),
                expected_state=state,
                code_received_future=code_received,
            )

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=callback_port,
            log_level="error",
            access_log=False,
        )
        server = uvicorn.Server(config)

        # We need to run the server in a way that we can get the port and shut it down
        server_task = asyncio.create_task(server.serve())

        # Wait for server to start and get port
        while not server.started:
            await asyncio.sleep(0.01)
            if server_task.done():
                await server_task  # Raise exception if failed to start
                break

        # Actual port if 0 was passed
        actual_port = 0
        if hasattr(server, "servers") and server.servers:
            for socket in server.servers[0].sockets:
                actual_port = socket.getsockname()[1]
                break
        else:
            actual_port = callback_port

        redirect_uri = f"http://localhost:{actual_port}/oauth2callback"
        auth_url = self._build_auth_url(state, redirect_uri)

        # 2. Open browser or print URL
        if open_browser:
            logger.info("Opening browser for OAuth authorization...")
            webbrowser.open(auth_url)
        else:
            logger.info(
                f"Please visit this URL to authorize the application:\n\n{auth_url}\n"
            )

        try:
            # 3. Wait for code
            code = await asyncio.wait_for(code_received, timeout=timeout)

            # 4. Exchange code for tokens
            token_data = await self._exchange_code(code, redirect_uri)

            # 5. Fetch user info (email)
            user_info = await self._fetch_userinfo(token_data["access_token"])
            email = user_info["email"]

            # 6. Prepare StoredAccount
            if not account_id:
                account_id = self._generate_account_id_from_email(email)
            else:
                # Validate and sanitize provided account_id if needed
                if not _ACCOUNT_ID_REGEX.match(account_id):
                    original_id = account_id
                    account_id = self._sanitize_account_id(account_id)
                    warning_msg = (
                        f"\nWarning: Account ID '{original_id}' contains invalid characters. "
                        f"Sanitized to '{account_id}'. "
                        f"Account IDs must be alphanumeric with hyphens/underscores only.\n"
                    )
                    logger.warning(warning_msg.strip())


            # Check if account already exists
            existing = await self._storage.get_account(account_id)
            if existing:
                account = existing.with_updated_tokens(
                    access_token=token_data["access_token"],
                    expiry_date=int(time.time() * 1000)
                    + token_data["expires_in"] * 1000,
                    refresh_token=token_data.get("refresh_token"),
                )
            else:
                account = StoredAccount(
                    account_id=account_id,
                    email=email,
                    access_token=token_data["access_token"],
                    refresh_token=token_data["refresh_token"],
                    scope=token_data["scope"],
                    expiry_date=int(time.time() * 1000)
                    + token_data["expires_in"] * 1000,
                )

            # 7. Save and return
            await self._storage.save_account(account)
            return account

        except asyncio.TimeoutError:
            raise OAuthError(
                f"Authorization timed out after {timeout} seconds"
            ) from None
        finally:
            server.should_exit = True
            await server_task

    async def _handle_callback_logic(
        self,
        received_state: str | None,
        code: str | None,
        error: str | None,
        expected_state: str,
        code_received_future: asyncio.Future[str],
    ) -> RedirectResponse:
        """Handle the OAuth callback logic.

        Args:
            received_state: State parameter received from Google
            code: Authorization code received from Google
            error: Error parameter received from Google
            expected_state: The state parameter we sent
            code_received_future: Future to set the result or exception

        Returns:
            RedirectResponse to success or failure page
        """
        if error:
            if not code_received_future.done():
                code_received_future.set_exception(
                    OAuthError(f"OAuth error from Google: {error}", error_code=error)
                )
            return RedirectResponse(url=FAILURE_REDIRECT)

        try:
            self._validate_state(expected_state, received_state)
        except OAuthError as e:
            if not code_received_future.done():
                code_received_future.set_exception(e)
            return RedirectResponse(url=FAILURE_REDIRECT)

        if not code:
            if not code_received_future.done():
                code_received_future.set_exception(
                    OAuthError("No authorization code received")
                )
            return RedirectResponse(url=FAILURE_REDIRECT)

        if not code_received_future.done():
            code_received_future.set_result(code)
        return RedirectResponse(url=SUCCESS_REDIRECT)

    def _generate_state(self) -> str:
        """Generate a cryptographically strong state parameter."""
        return secrets.token_hex(32)

    def _build_auth_url(self, state: str, redirect_uri: str) -> str:
        """Build the Google OAuth authorization URL."""
        params = {
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(OAUTH_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        data = {
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

        try:
            response = await self._http_client.post(TOKEN_URL, data=data)
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
        except httpx.HTTPStatusError as e:
            error_data = {}
            with contextlib.suppress(Exception):
                error_data = e.response.json()

            error_msg = (
                error_data.get("error_description") or error_data.get("error") or str(e)
            )
            raise OAuthError(
                f"Failed to exchange authorization code: {error_msg}"
            ) from e
        except Exception as e:
            raise OAuthError(f"Network error during code exchange: {e}") from e

    async def _fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        """Fetch user profile information using access token."""
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = await self._http_client.get(USERINFO_URL, headers=headers)
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
        except Exception as e:
            raise OAuthError(f"Failed to fetch user information: {e}") from e

    def _validate_state(self, expected: str, received: str | None) -> None:
        """Validate that the received state matches the expected state."""
        if not received or received != expected:
            raise OAuthError(
                "State parameter mismatch. Possible CSRF attack.",
                error_code="state_mismatch",
            )

    def _sanitize_account_id(self, account_id: str) -> str:
        """Sanitize an account_id to match validation pattern.

        Replaces invalid characters with underscores and ensures it starts
        with alphanumeric character.

        Args:
            account_id: Account ID to sanitize

        Returns:
            Sanitized account_id that matches validation pattern
        """
        # Replace non-alphanumeric (except hyphens/underscores) with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", account_id)
        # Ensure it doesn't start with hyphen/underscore (per model validation)
        if sanitized and sanitized[0] in ("-", "_"):
            sanitized = "user_" + sanitized
        # Truncate to max length
        return sanitized[:64]

    def _generate_account_id_from_email(self, email: str) -> str:
        """Generate a valid account_id from an email address."""
        # Take local part of email and sanitize
        local_part = email.split("@")[0]
        # Replace non-alphanumeric with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", local_part)
        # Ensure it doesn't start with hyphen/underscore (per model validation)
        if sanitized and sanitized[0] in ("-", "_"):
            sanitized = "user_" + sanitized
        return sanitized[:64]
