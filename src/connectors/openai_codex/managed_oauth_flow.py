"""Browser OAuth flow for OpenAI Codex managed accounts."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import logging
import re
import secrets
import time
import uuid
import webbrowser
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from src.connectors.openai_codex.managed_oauth_constants import (
    DEFAULT_OAUTH_CALLBACK_PATH,
    DEFAULT_OAUTH_CALLBACK_PORT,
    OPENAI_OAUTH_AUTHORIZE_URL,
    OPENAI_OAUTH_CLIENT_ID,
    OPENAI_OAUTH_SCOPES,
    OPENAI_OAUTH_TOKEN_URL,
)
from src.connectors.openai_codex.managed_oauth_jwt import (
    extract_chatgpt_account_id_from_token,
    extract_email_from_token,
    extract_expiry_ms_from_token,
)
from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService

logger = logging.getLogger(__name__)

_ACCOUNT_SANITIZE_REGEX = re.compile(r"[^a-zA-Z0-9_-]")


class ManagedOAuthFlowError(RuntimeError):
    """Raised when the interactive OAuth authorization flow fails."""


class ManagedOAuthFlowService:
    """Runs local callback server and exchanges auth code for tokens."""

    def __init__(
        self,
        storage: ManagedOAuthStorageService,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._storage = storage
        self._http_client = http_client

    async def authorize(
        self,
        *,
        account_id: str | None = None,
        port: int | None = None,
        timeout_seconds: int = 180,
        open_browser: bool = True,
    ) -> ManagedOAuthAccount:
        """Run OAuth authorization flow and persist resulting account."""
        state = self._generate_state()
        code_verifier, code_challenge = self._generate_pkce_pair()
        callback_port = (
            int(port) if port is not None else int(DEFAULT_OAUTH_CALLBACK_PORT)
        )

        app = FastAPI()
        code_future: asyncio.Future[str] = asyncio.Future()

        async def oauth_callback(request: Request) -> HTMLResponse:
            return await self._handle_callback(
                request=request,
                expected_state=state,
                code_future=code_future,
            )

        # Use Codex CLI callback path by default; keep legacy alias for compatibility.
        app.add_api_route(DEFAULT_OAUTH_CALLBACK_PATH, oauth_callback, methods=["GET"])
        app.add_api_route("/oauth2callback", oauth_callback, methods=["GET"])

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=callback_port,
            log_level="error",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        # Wait for uvicorn startup and discover selected port.
        while not server.started:
            await asyncio.sleep(0.01)
            if server_task.done():
                with contextlib.suppress(Exception):
                    await server_task
                raise ManagedOAuthFlowError(
                    "OAuth callback server failed to start. "
                    "Try a different --port or close the process using the current port."
                )

        actual_port = callback_port
        if hasattr(server, "servers") and server.servers:
            sockets = server.servers[0].sockets
            if sockets:
                actual_port = int(sockets[0].getsockname()[1])
        redirect_uri = self._build_redirect_uri(actual_port)
        auth_url = self._build_authorize_url(
            state=state,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
        )

        if open_browser:
            logger.info("Opening browser for OpenAI Codex OAuth authorization")
            webbrowser.open(auth_url)
        else:
            logger.info("Open this URL to authorize:\n%s", auth_url)

        try:
            code = await asyncio.wait_for(code_future, timeout=timeout_seconds)
            tokens = await self._exchange_code(
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
            return await self._build_and_save_account(
                tokens=tokens,
                requested_account_id=account_id,
            )
        except asyncio.TimeoutError as exc:
            raise ManagedOAuthFlowError(
                f"Authorization timed out after {timeout_seconds} seconds"
            ) from exc
        finally:
            server.should_exit = True
            with contextlib.suppress(Exception):
                await server_task

    async def _handle_callback(
        self,
        *,
        request: Request,
        expected_state: str,
        code_future: asyncio.Future[str],
    ) -> HTMLResponse:
        error = request.query_params.get("error")
        received_state = request.query_params.get("state")
        code = request.query_params.get("code")

        if error:
            if not code_future.done():
                code_future.set_exception(
                    ManagedOAuthFlowError(f"OAuth provider returned error: {error}")
                )
            return HTMLResponse(
                "<h2>OpenAI authorization failed.</h2>"
                "<p>You can close this window and check the terminal output.</p>",
                status_code=400,
            )

        if not received_state or received_state != expected_state:
            if not code_future.done():
                code_future.set_exception(
                    ManagedOAuthFlowError(
                        "OAuth state mismatch detected; aborting authorization"
                    )
                )
            return HTMLResponse(
                "<h2>State mismatch.</h2>"
                "<p>Authorization request was rejected for safety.</p>",
                status_code=400,
            )

        if not code:
            if not code_future.done():
                code_future.set_exception(
                    ManagedOAuthFlowError("No authorization code received")
                )
            return HTMLResponse(
                "<h2>Missing code.</h2>"
                "<p>Authorization did not return a valid code.</p>",
                status_code=400,
            )

        if not code_future.done():
            code_future.set_result(code)
        return HTMLResponse(
            "<h2>Authorization complete.</h2>"
            "<p>You can close this window and return to the terminal.</p>",
            status_code=200,
        )

    def _generate_state(self) -> str:
        return secrets.token_urlsafe(32)

    def _generate_pkce_pair(self) -> tuple[str, str]:
        verifier_bytes = secrets.token_bytes(32)
        code_verifier = (
            base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")
        )
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return code_verifier, code_challenge

    def _build_authorize_url(
        self,
        *,
        state: str,
        redirect_uri: str,
        code_challenge: str,
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": OPENAI_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": " ".join(OPENAI_OAUTH_SCOPES),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
        }
        return f"{OPENAI_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    def _build_redirect_uri(self, callback_port: int) -> str:
        return f"http://localhost:{callback_port}{DEFAULT_OAUTH_CALLBACK_PATH}"

    async def _exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        # Token POST uses OPENAI_OAUTH_TOKEN_URL (hardcoded OpenAI endpoint).
        # httpx.AsyncClient defaults ``follow_redirects`` to False, so redirects are
        # not followed unless explicitly enabled; add ``assert_url_safe_for_egress``
        # only if this URL ever becomes a configurable setting.
        form_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": OPENAI_OAUTH_CLIENT_ID,
            "code_verifier": code_verifier,
        }

        if self._http_client is None:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    OPENAI_OAUTH_TOKEN_URL,
                    data=form_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30.0,
                )
        else:
            response = await self._http_client.post(
                OPENAI_OAUTH_TOKEN_URL,
                data=form_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

        if response.status_code >= 400:
            body = response.text
            body_preview = body[:300] + "..." if len(body) > 300 else body
            raise ManagedOAuthFlowError(
                f"Token exchange failed with HTTP {response.status_code}: {body_preview}"
            )

        try:
            payload = cast(dict[str, Any], response.json())
        except Exception as exc:
            raise ManagedOAuthFlowError(
                f"Token exchange response is not valid JSON: {exc}"
            ) from exc
        return payload

    async def _build_and_save_account(
        self,
        *,
        tokens: dict[str, Any],
        requested_account_id: str | None,
    ) -> ManagedOAuthAccount:
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ManagedOAuthFlowError("OAuth response missing access_token")
        refresh_token = tokens.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise ManagedOAuthFlowError("OAuth response missing refresh_token")

        token_type = tokens.get("token_type")
        scope = tokens.get("scope")
        token_type_value = token_type if isinstance(token_type, str) else "Bearer"
        scope_value = (
            scope if isinstance(scope, str) and scope else " ".join(OPENAI_OAUTH_SCOPES)
        )

        expires_in_raw = tokens.get("expires_in")
        expiry_ms: int | None = None
        if isinstance(expires_in_raw, int | float):
            expiry_ms = int(time.time() * 1000) + (int(float(expires_in_raw)) * 1000)
        if expiry_ms is None:
            expiry_ms = extract_expiry_ms_from_token(access_token)

        id_token = tokens.get("id_token")
        id_token_value = id_token if isinstance(id_token, str) and id_token else None

        email = extract_email_from_token(access_token)
        if email is None and id_token_value is not None:
            email = extract_email_from_token(id_token_value)

        chatgpt_account_id = extract_chatgpt_account_id_from_token(access_token)
        if chatgpt_account_id is None and id_token_value is not None:
            chatgpt_account_id = extract_chatgpt_account_id_from_token(id_token_value)

        resolved_account_id = self._resolve_account_id(
            requested_account_id=requested_account_id,
            email=email,
            chatgpt_account_id=chatgpt_account_id,
        )

        existing = await self._storage.get_account(resolved_account_id)
        if existing is None:
            account = ManagedOAuthAccount(
                account_id=resolved_account_id,
                email=email,
                access_token=access_token,
                refresh_token=refresh_token,
                token_type=token_type_value,
                scope=scope_value,
                expiry_date=expiry_ms,
                chatgpt_account_id=chatgpt_account_id,
            )
        else:
            account = existing.with_updated_tokens(
                access_token=access_token,
                refresh_token=refresh_token,
                expiry_date=expiry_ms,
                email=email,
                chatgpt_account_id=chatgpt_account_id,
                scope=scope_value,
                token_type=token_type_value,
            )
        await self._storage.save_account(account)
        return account

    def _resolve_account_id(
        self,
        *,
        requested_account_id: str | None,
        email: str | None,
        chatgpt_account_id: str | None,
    ) -> str:
        if requested_account_id and requested_account_id.strip():
            return self._sanitize_account_id(requested_account_id.strip())
        if chatgpt_account_id:
            return self._sanitize_account_id(chatgpt_account_id)
        if email and "@" in email:
            return self._sanitize_account_id(email.split("@", 1)[0])
        return f"codex-{uuid.uuid4().hex[:12]}"

    def _sanitize_account_id(self, raw: str) -> str:
        cleaned = _ACCOUNT_SANITIZE_REGEX.sub("_", raw)
        if not cleaned:
            cleaned = f"acct_{uuid.uuid4().hex[:8]}"
        if cleaned[0] in {"_", "-"}:
            cleaned = f"user{cleaned}"
        return cleaned[:64]
