"""
Integration tests for Qwen OAuth backend.

These tests require:
1. qwen-code CLI to be installed and authenticated
2. Valid OAuth tokens in ~/.qwen/oauth_creds.json
3. Network access to portal.qwen.ai

Run with: pytest -m "integration and network" tests/integration/test_qwen_oauth_integration.py
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.main import build_app

# Mark all tests in this module as integration and network tests
pytestmark = [pytest.mark.integration, pytest.mark.network]


# Check if OAuth credentials are available
def _has_qwen_oauth_credentials() -> bool:
    """Check if Qwen OAuth credentials are available."""
    home_dir = Path.home()
    creds_path = home_dir / ".qwen" / "oauth_creds.json"

    if not creds_path.exists():
        return False

    try:
        with open(creds_path, encoding="utf-8") as f:
            creds = json.load(f)
        return bool(creds.get("access_token") and creds.get("refresh_token"))
    except Exception:
        return False


# Skip all tests if OAuth credentials are not available
QWEN_OAUTH_AVAILABLE = _has_qwen_oauth_credentials()


class TestQwenOAuthConnector:
    """Test the Qwen OAuth connector directly."""

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    @pytest.mark.asyncio
    async def test_qwen_oauth_connector_initialization(self):
        """Test that the Qwen OAuth connector can be initialized."""
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector

        async with httpx.AsyncClient(timeout=30.0) as client:
            connector = QwenOAuthConnector(client)

            await connector.initialize()

            assert connector.is_functional
            assert len(connector.get_available_models()) > 0
            assert "qwen3-coder-plus" in connector.get_available_models()

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    @pytest.mark.asyncio
    async def test_qwen_oauth_chat_completion(self):
        """Test basic chat completion with Qwen OAuth connector."""
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector
        from src.models import ChatCompletionRequest, ChatMessage

        async with httpx.AsyncClient(timeout=30.0) as client:
            connector = QwenOAuthConnector(client)
            await connector.initialize()

            # Create test request
            test_message = ChatMessage(
                role="user",
                content="Respond with exactly 'Test successful' and nothing else.",
            )

            request_data = ChatCompletionRequest(
                model="qwen3-coder-plus",
                messages=[test_message],
                max_tokens=10,
                temperature=0.1,
                stream=False,
            )

            # Make request
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            # Verify response
            assert isinstance(result, tuple)
            response, headers = result

            assert "choices" in response
            assert len(response["choices"]) > 0
            assert "message" in response["choices"][0]
            assert "content" in response["choices"][0]["message"]

            content = response["choices"][0]["message"]["content"]
            assert isinstance(content, str)
            assert len(content) > 0

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    @pytest.mark.asyncio
    async def test_qwen_oauth_streaming_completion(self):
        """Test streaming chat completion with Qwen OAuth connector."""
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector
        from src.models import ChatCompletionRequest, ChatMessage
        from starlette.responses import StreamingResponse

        async with httpx.AsyncClient(timeout=30.0) as client:
            connector = QwenOAuthConnector(client)
            await connector.initialize()

            # Create test request
            test_message = ChatMessage(
                role="user", content="Count from 1 to 3, one number per line."
            )

            request_data = ChatCompletionRequest(
                model="qwen3-coder-plus",
                messages=[test_message],
                max_tokens=20,
                temperature=0.1,
                stream=True,
            )

            # Make streaming request
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            # Verify streaming response
            assert isinstance(result, StreamingResponse)
            assert result.media_type == "text/event-stream"


class TestQwenOAuthProxyIntegration:
    """Test Qwen OAuth backend integration with the proxy."""

    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for Qwen OAuth backend."""
        with patch("src.core.config.load_dotenv"):
            # Set up environment for testing
            os.environ["LLM_BACKEND"] = "qwen-oauth"
            os.environ["DISABLE_AUTH"] = "true"  # Disable proxy auth for testing
            os.environ["DISABLE_ACCOUNTING"] = "true"  # Disable accounting for testing
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"

            app = build_app()
            yield app

    @pytest.fixture
    def qwen_oauth_client(self, qwen_oauth_app):
        """TestClient for Qwen OAuth configured app."""
        with TestClient(qwen_oauth_app) as client:
            yield client

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_qwen_oauth_backend_initialization(self, qwen_oauth_app):
        """Test that the Qwen OAuth backend is properly initialized in the app."""
        # Check if qwen-oauth is in functional backends
        assert hasattr(qwen_oauth_app.state, "functional_backends")

        # The backend should be functional if credentials are available
        if QWEN_OAUTH_AVAILABLE:
            from src.constants import BackendType

            # The most important check: backend should be in functional_backends
            assert BackendType.QWEN_OAUTH in qwen_oauth_app.state.functional_backends

            # Check that the backend object exists (if it's stored in app state)
            if hasattr(qwen_oauth_app.state, "qwen_oauth_backend"):
                assert qwen_oauth_app.state.qwen_oauth_backend is not None
                assert qwen_oauth_app.state.qwen_oauth_backend.is_functional
            else:
                # Backend might be created during lifespan but not stored in state
                # This is acceptable as long as it's in functional_backends
                pass

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_qwen_oauth_chat_completion_via_proxy(self, qwen_oauth_client):
        """Test chat completion through the proxy using Qwen OAuth backend."""
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user",
                    "content": "Respond with exactly 'Proxy test successful' and nothing else.",
                }
            ],
            "max_tokens": 10,
            "temperature": 0.1,
            "stream": False,
        }

        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)

        assert response.status_code == 200

        result = response.json()
        assert "choices" in result
        assert len(result["choices"]) > 0
        assert "message" in result["choices"][0]
        assert "content" in result["choices"][0]["message"]

        content = result["choices"][0]["message"]["content"]
        assert isinstance(content, str)
        assert len(content) > 0

        # Check usage tracking
        if "usage" in result:
            usage = result["usage"]
            assert "prompt_tokens" in usage
            assert "completion_tokens" in usage
            assert "total_tokens" in usage
            assert usage["total_tokens"] > 0

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_qwen_oauth_streaming_via_proxy(self, qwen_oauth_client):
        """Test streaming chat completion through the proxy using Qwen OAuth backend."""
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {"role": "user", "content": "Count from 1 to 3, one number per line."}
            ],
            "max_tokens": 20,
            "temperature": 0.1,
            "stream": True,
        }

        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Verify we get streaming chunks
        chunks_received = 0
        for line in response.iter_lines():
            if line:
                line_str = line if isinstance(line, str) else line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_part = line_str[6:]  # Remove 'data: ' prefix
                    if data_part.strip() == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(data_part)
                        if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                            chunks_received += 1
                    except json.JSONDecodeError:
                        continue

        assert chunks_received > 0, "Should receive at least one streaming chunk"

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_qwen_oauth_model_override_command(self, qwen_oauth_client):
        """Test model override via in-chat command with Qwen OAuth backend."""
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user",
                    "content": "!/set(model=qwen-oauth:qwen3-coder-flash) Respond with 'Model override test' and nothing else.",
                }
            ],
            "max_tokens": 10,
            "temperature": 0.1,
            "stream": False,
        }

        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)

        # The command should be processed, even if the model switch fails
        assert response.status_code == 200

        result = response.json()
        assert "choices" in result
        assert len(result["choices"]) > 0

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_qwen_oauth_backend_selection_command(self, qwen_oauth_client):
        """Test backend selection via in-chat command."""
        request_payload = {
            "model": "openrouter:gpt-3.5-turbo",  # Start with different backend
            "messages": [
                {
                    "role": "user",
                    "content": "!/set(backend=qwen-oauth) Now respond with 'Backend switch successful' and nothing else.",
                }
            ],
            "max_tokens": 10,
            "temperature": 0.1,
            "stream": False,
        }

        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)

        # The command should be processed
        assert response.status_code == 200

        result = response.json()
        assert "choices" in result
        assert len(result["choices"]) > 0


class TestQwenOAuthErrorHandling:
    """Test error handling scenarios for Qwen OAuth backend."""

    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for Qwen OAuth backend."""
        with patch("src.core.config.load_dotenv"):
            os.environ["LLM_BACKEND"] = "qwen-oauth"
            os.environ["DISABLE_AUTH"] = "true"
            os.environ["DISABLE_ACCOUNTING"] = "true"
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"

            app = build_app()
            yield app

    @pytest.fixture
    def qwen_oauth_client(self, qwen_oauth_app):
        """TestClient for Qwen OAuth configured app."""
        with TestClient(qwen_oauth_app) as client:
            yield client

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_invalid_model_name(self, qwen_oauth_client):
        """Test handling of invalid model names."""
        request_payload = {
            "model": "qwen-oauth:invalid-model-name",
            "messages": [{"role": "user", "content": "This should fail"}],
            "max_tokens": 10,
            "temperature": 0.1,
            "stream": False,
        }

        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)

        # Should get an error response but still be a valid HTTP response
        assert response.status_code in [400, 404, 422]  # Various possible error codes

    def test_qwen_oauth_without_credentials(self):
        """Test Qwen OAuth backend behavior when credentials are not available."""
        # This test runs even without credentials to test the fallback behavior
        from unittest.mock import patch

        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector

        async def run_test():
            # Mock the credentials file to not exist
            with patch("pathlib.Path.exists", return_value=False):
                async with httpx.AsyncClient(timeout=30.0) as client:
                    connector = QwenOAuthConnector(client)

                    # Verify it inherits from OpenAIConnector
                    from src.connectors.openai import OpenAIConnector

                    assert isinstance(connector, OpenAIConnector)

                    await connector.initialize()

                    # Should not be functional without credentials
                    assert not connector.is_functional
                    assert len(connector.get_available_models()) == 0

        import asyncio

        asyncio.run(run_test())


# Helper functions for test discovery
def test_qwen_oauth_credentials_available():
    """Test helper to check if Qwen OAuth credentials are available for testing."""
    if QWEN_OAUTH_AVAILABLE:
        print("✅ Qwen OAuth credentials are available for testing")

        # Print some info about the credentials (without sensitive data)
        home_dir = Path.home()
        creds_path = home_dir / ".qwen" / "oauth_creds.json"

        try:
            with open(creds_path, encoding="utf-8") as f:
                creds = json.load(f)

            print("📋 Credential info:")
            print(
                f"   - Has access token: {'✅' if creds.get('access_token') else '❌'}"
            )
            print(
                f"   - Has refresh token: {'✅' if creds.get('refresh_token') else '❌'}"
            )
            print(f"   - Token type: {creds.get('token_type', 'N/A')}")
            print(f"   - Resource URL: {creds.get('resource_url', 'Using default')}")

            if creds.get("expiry_date"):
                import time

                expiry_time = creds["expiry_date"] / 1000
                current_time = time.time()
                if expiry_time > current_time:
                    remaining = int(expiry_time - current_time)
                    print(f"   - Token expires in: {remaining} seconds")
                else:
                    print(
                        f"   - Token expired: {int(current_time - expiry_time)} seconds ago"
                    )

        except Exception as e:
            print(f"⚠️  Could not read credential details: {e}")
    else:
        pytest.skip(
            "Qwen OAuth credentials not available. Run 'qwen-code --auth' to authenticate."
        )


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-m", "integration and network"])
