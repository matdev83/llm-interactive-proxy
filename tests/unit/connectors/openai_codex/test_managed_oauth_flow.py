"""Unit tests for managed OpenAI Codex OAuth flow URL construction."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from src.connectors.openai_codex.managed_oauth_constants import (
    DEFAULT_OAUTH_CALLBACK_PATH,
    DEFAULT_OAUTH_CALLBACK_PORT,
    OPENAI_OAUTH_AUTHORIZE_URL,
    OPENAI_OAUTH_CLIENT_ID,
    OPENAI_OAUTH_SCOPES,
)
from src.connectors.openai_codex.managed_oauth_flow import ManagedOAuthFlowService
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService


def test_build_redirect_uri_matches_codex_cli_shape(tmp_path) -> None:
    service = ManagedOAuthFlowService(ManagedOAuthStorageService(tmp_path))

    redirect_uri = service._build_redirect_uri(DEFAULT_OAUTH_CALLBACK_PORT)

    assert (
        redirect_uri
        == f"http://localhost:{DEFAULT_OAUTH_CALLBACK_PORT}{DEFAULT_OAUTH_CALLBACK_PATH}"
    )


def test_build_authorize_url_includes_codex_required_params(tmp_path) -> None:
    service = ManagedOAuthFlowService(ManagedOAuthStorageService(tmp_path))
    redirect_uri = service._build_redirect_uri(DEFAULT_OAUTH_CALLBACK_PORT)

    auth_url = service._build_authorize_url(
        state="state_123",
        redirect_uri=redirect_uri,
        code_challenge="challenge_123",
    )

    parsed = urlparse(auth_url)
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == OPENAI_OAUTH_AUTHORIZE_URL
    )

    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == [OPENAI_OAUTH_CLIENT_ID]
    assert query["redirect_uri"] == [redirect_uri]
    assert query["scope"] == [" ".join(OPENAI_OAUTH_SCOPES)]
    assert query["code_challenge"] == ["challenge_123"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["id_token_add_organizations"] == ["true"]
    assert query["codex_cli_simplified_flow"] == ["true"]
    assert query["state"] == ["state_123"]
