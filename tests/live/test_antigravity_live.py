"""
Live integration tests for the Antigravity backend.

These tests make REAL API calls to the Antigravity sandbox endpoint using
credentials from the local Antigravity app installation.

Requirements:
- Antigravity app must be installed and logged in
- OAuth credentials must be present in the Antigravity state database
- LIVE_TESTS_ENABLED=true environment variable must be set

Run with:
    LIVE_TESTS_ENABLED=true pytest tests/live/test_antigravity_live.py -v
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from src.connectors.gemini_oauth_antigravity import (
    ANTIGRAVITY_AUTH_KEY,
    GeminiOAuthAntigravityConnector,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService

pytestmark = pytest.mark.live


def _find_antigravity_db() -> Path | None:
    """Find the Antigravity state database path."""
    candidates: list[Path] = []

    # Windows
    appdata = os.getenv("APPDATA")
    if appdata:
        candidates.append(
            Path(appdata) / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
        )

    # Linux/XDG
    xdg_config = os.getenv("XDG_CONFIG_HOME")
    if xdg_config:
        candidates.append(
            Path(xdg_config) / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
        )

    home = Path.home()
    candidates.append(
        home / ".config" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
    )

    # macOS
    candidates.append(
        home
        / "Library"
        / "Application Support"
        / "Antigravity"
        / "User"
        / "globalStorage"
        / "state.vscdb"
    )

    for path in candidates:
        if path.exists():
            return path

    return None


def _has_antigravity_credentials() -> bool:
    """Check if Antigravity credentials are available."""
    import json
    import sqlite3

    db_path = _find_antigravity_db()
    if not db_path:
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT value FROM ItemTable WHERE key='{ANTIGRAVITY_AUTH_KEY}' LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return False

        data = json.loads(row[0])
        return "apiKey" in data or "access_token" in data
    except Exception:
        return False


@pytest.fixture(scope="session")
def antigravity_available() -> bool:
    """Check if Antigravity credentials are available."""
    return _has_antigravity_credentials()


@pytest.fixture
def require_antigravity(antigravity_available: bool) -> None:
    """Skip test if Antigravity credentials are not available."""
    if not antigravity_available:
        pytest.skip(
            "Antigravity credentials not available. "
            "Ensure the Antigravity app is installed and logged in."
        )


@pytest.fixture
async def connector() -> AsyncIterator[GeminiOAuthAntigravityConnector]:
    """Create and initialize a real Antigravity connector."""
    config = AppConfig()
    translation_service = TranslationService()

    async with httpx.AsyncClient() as client:
        conn = GeminiOAuthAntigravityConnector(
            client=client,
            config=config,
            translation_service=translation_service,
        )
        await conn.initialize()
        yield conn


class TestAntigravityLiveNonStreaming:
    """Live tests for non-streaming Antigravity API calls."""

    @pytest.mark.asyncio
    async def test_connector_initializes_with_real_credentials(
        self, require_antigravity: None, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Verify that the connector initializes successfully with real credentials."""
        assert connector.is_functional
        assert connector._oauth_credentials is not None
        assert "access_token" in connector._oauth_credentials

    @pytest.mark.asyncio
    async def test_non_streaming_simple_prompt(
        self, require_antigravity: None, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Test a simple non-streaming request to claude-sonnet-4-5."""
        request = ChatRequest(
            model="claude-sonnet-4-5",
            messages=[
                ChatMessage(
                    role="user",
                    content="What is 2 + 2? Reply with just the number.",
                )
            ],
            max_tokens=10,
            temperature=0.1,
            stream=False,
        )

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model=request.model,
        )

        # Verify we got a response
        assert response is not None
        assert hasattr(response, "content")

        # Extract and verify content
        content = response.content
        assert content is not None

        # Content should contain "4" somewhere
        content_str = str(content)
        assert "4" in content_str, f"Expected '4' in response, got: {content_str}"

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="gemini-2.5-pro may return empty responses on Antigravity sandbox"
    )
    async def test_non_streaming_with_gemini_model(
        self, require_antigravity: None, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Test a simple non-streaming request to gemini-2.5-pro.

        Note: This test is marked xfail because the Antigravity sandbox
        sometimes returns empty responses for Gemini models.
        """
        request = ChatRequest(
            model="gemini-2.5-pro",
            messages=[
                ChatMessage(
                    role="user",
                    content="What is 3 + 3? Reply with just the number.",
                )
            ],
            max_tokens=10,
            temperature=0.1,
            stream=False,
        )

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model=request.model,
        )

        assert response is not None
        assert hasattr(response, "content")

        content_str = str(response.content)
        assert "6" in content_str, f"Expected '6' in response, got: {content_str}"


class TestAntigravityLiveStreaming:
    """Live tests for streaming Antigravity API calls."""

    @pytest.mark.asyncio
    async def test_streaming_simple_prompt(
        self, require_antigravity: None, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Test a simple streaming request to claude-sonnet-4-5."""
        request = ChatRequest(
            model="claude-sonnet-4-5",
            messages=[
                ChatMessage(
                    role="user",
                    content="Count from 1 to 3, one number per line.",
                )
            ],
            max_tokens=30,
            temperature=0.1,
            stream=True,
        )

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model=request.model,
        )

        # Response should be a streaming envelope
        assert response is not None
        assert hasattr(response, "content")

        # Collect streaming chunks
        chunks: list[str] = []
        chunk_count = 0

        async for chunk in response.content:
            chunk_count += 1
            if hasattr(chunk, "content") and chunk.content:
                content = chunk.content
                if isinstance(content, dict):
                    choices = content.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            chunks.append(text)

        full_response = "".join(chunks)

        # Should have received multiple chunks
        assert chunk_count > 0, "Expected to receive streaming chunks"

        # Response should contain the numbers
        assert "1" in full_response, f"Expected '1' in response: {full_response}"
        assert "2" in full_response, f"Expected '2' in response: {full_response}"
        assert "3" in full_response, f"Expected '3' in response: {full_response}"

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="gemini-2.5-pro may return empty responses on Antigravity sandbox"
    )
    async def test_streaming_with_gemini_model(
        self, require_antigravity: None, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Test a streaming request to gemini-2.5-pro.

        Note: This test is marked xfail because the Antigravity sandbox
        sometimes returns empty responses for Gemini models.
        """
        request = ChatRequest(
            model="gemini-2.5-pro",
            messages=[
                ChatMessage(
                    role="user",
                    content="Say 'Hello World' and nothing else.",
                )
            ],
            max_tokens=20,
            temperature=0.1,
            stream=True,
        )

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model=request.model,
        )

        # Collect streaming response
        chunks: list[str] = []

        async for chunk in response.content:
            if hasattr(chunk, "content") and chunk.content:
                content = chunk.content
                if isinstance(content, dict):
                    choices = content.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            chunks.append(text)

        full_response = "".join(chunks).lower()

        # Should contain hello world
        assert (
            "hello" in full_response
        ), f"Expected 'hello' in response: {full_response}"


class TestAntigravityLiveErrorHandling:
    """Live tests for error handling with real API."""

    @pytest.mark.asyncio
    async def test_quota_error_contains_reset_info(
        self, require_antigravity: None, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """
        If a quota error occurs, verify it contains reset information.

        Note: This test may pass or get a real response depending on quota state.
        """
        request = ChatRequest(
            model="claude-sonnet-4-5",
            messages=[
                ChatMessage(
                    role="user",
                    content="Hi",
                )
            ],
            max_tokens=5,
            temperature=0.1,
            stream=False,
        )

        try:
            response = await connector.chat_completions(
                request_data=request,
                processed_messages=request.messages,
                effective_model=request.model,
            )
            # If we got a response, the test passes (quota is available)
            assert response is not None
        except Exception as e:
            error_str = str(e).lower()
            # If we got a quota error, verify it has useful info
            if "429" in error_str or "quota" in error_str:
                # The error should contain reset information
                assert (
                    "reset" in error_str or "exhausted" in error_str
                ), f"Quota error should contain reset info: {e}"
            else:
                # Re-raise unexpected errors
                raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
