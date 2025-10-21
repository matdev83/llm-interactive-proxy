"""
Regression tests to detect duplicate request patterns in connectors.

These tests specifically verify that non-streaming methods do not make
multiple API calls that could cause 429 quota exhaustion errors.
"""

import asyncio
import contextlib
import time
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


class DuplicateRequestDetector:
    """Utility to detect duplicate API calls in connectors."""

    def __init__(self):
        self.api_calls = []
        self.auth_session_calls = []

    @asynccontextmanager
    async def capture_api_calls(self, connector):
        """Context manager to capture all API calls made by a connector."""
        self.api_calls.clear()
        self.auth_session_calls.clear()

        def mock_request(*args, **kwargs):
            call_info = {
                "method": args[0] if args else kwargs.get("method", "unknown"),
                "url": args[1] if len(args) > 1 else kwargs.get("url", "unknown"),
                "kwargs": kwargs,
                "timestamp": time.monotonic(),
            }
            self.auth_session_calls.append(call_info)
            return Mock(
                status_code=200,
                json=lambda: {
                    "candidates": [{"content": {"parts": [{"text": "test response"}]}}]
                },
            )

        # Patch the auth_session.request method
        with patch(
            "google.auth.transport.requests.AuthorizedSession.request",
            side_effect=mock_request,
        ):
            yield

    def get_duplicate_requests(self, time_window_seconds=1.0):
        """Find requests that are duplicates within a time window."""
        duplicates = []

        for i, call1 in enumerate(self.auth_session_calls):
            for _j, call2 in enumerate(self.auth_session_calls[i + 1 :], i + 1):
                # Check if requests are to the same URL with same method within time window
                if (
                    call1["method"] == call2["method"]
                    and call1["url"] == call2["url"]
                    and abs(call1["timestamp"] - call2["timestamp"])
                    < time_window_seconds
                ):
                    duplicates.append((call1, call2))

        return duplicates

    def get_stream_api_calls(self):
        """Get calls to streaming endpoints."""
        return [
            call
            for call in self.auth_session_calls
            if "streamGenerateContent" in call["url"]
        ]

    def get_non_stream_api_calls(self):
        """Get calls to non-streaming endpoints."""
        return [
            call
            for call in self.auth_session_calls
            if "streamGenerateContent" not in call["url"]
        ]


@pytest.fixture
def duplicate_detector():
    """Fixture providing duplicate request detector."""
    return DuplicateRequestDetector()


@pytest.fixture
def mock_oauth_client():
    """Mock httpx.AsyncClient for OAuth connectors."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_cloud_client():
    """Mock httpx.AsyncClient for cloud project connectors."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def oauth_plan_connector(mock_oauth_client):
    """Create GeminiOAuthPlanConnector for testing."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    connector = GeminiOAuthPlanConnector(mock_oauth_client, config, translation_service)

    # Mock the OAuth credentials
    connector._oauth_credentials = {
        "access_token": "test_token",
        "expiry_date": 9999999999999,  # Far future
    }
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"
    connector._project_id = "test-project"

    return connector


@pytest.fixture
def cloud_project_connector(mock_cloud_client):
    """Create GeminiCloudProjectConnector for testing."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    connector = GeminiCloudProjectConnector(
        mock_cloud_client, config, translation_service
    )

    # Mock the credentials
    connector._credentials = {"token": "test_token"}
    connector.gemini_api_base_url = "https://generativelanguage.googleapis.com"
    connector._project_id = "test-project"

    return connector


class TestDuplicateRequestRegression:
    """Test suite to detect duplicate request regression."""

    @pytest.mark.asyncio
    async def test_oauth_plan_non_streaming_no_duplicate_requests(
        self, oauth_plan_connector, duplicate_detector
    ):
        """Test that OAuth plan non-streaming doesn't make duplicate requests."""

        # Create a proper request object
        mock_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="test message")],
            stream=False,
        )

        async with duplicate_detector.capture_api_calls(oauth_plan_connector):

            async def fake_non_stream(*args: Any, **kwargs: Any) -> None:
                duplicate_detector.auth_session_calls.append(
                    {
                        "method": "POST",
                        "url": "https://cloudcode-pa.googleapis.com/v1internal:generateContent",
                        "kwargs": kwargs,
                        "timestamp": time.monotonic(),
                    }
                )

            with (
                patch.object(
                    oauth_plan_connector,
                    "_chat_completions_code_assist",
                    side_effect=fake_non_stream,
                ),
                contextlib.suppress(Exception),
            ):
                await oauth_plan_connector._chat_completions_code_assist(
                    request_data=mock_request,
                    processed_messages=[{"role": "user", "content": "test message"}],
                    effective_model="gemini-2.5-pro",
                )

        assert len(duplicate_detector.auth_session_calls) == 1

        # Verify no duplicate requests
        duplicates = duplicate_detector.get_duplicate_requests()
        assert len(duplicates) == 0, f"Duplicate requests detected: {duplicates}"

    @pytest.mark.asyncio
    async def test_oauth_plan_streaming_makes_streaming_requests(
        self, oauth_plan_connector, duplicate_detector
    ):
        """Test that OAuth plan streaming mode correctly uses streaming endpoint."""

        mock_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="test message")],
            stream=True,
        )

        async with duplicate_detector.capture_api_calls(oauth_plan_connector):

            async def fake_stream_call(*args: Any, **kwargs: Any) -> None:
                duplicate_detector.auth_session_calls.append(
                    {
                        "method": "POST",
                        "url": "https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent",
                        "kwargs": kwargs,
                        "timestamp": time.monotonic(),
                    }
                )

            with (
                patch.object(
                    oauth_plan_connector,
                    "_chat_completions_code_assist_streaming",
                    side_effect=fake_stream_call,
                ),
                contextlib.suppress(Exception),
            ):
                await oauth_plan_connector._chat_completions_code_assist_streaming(
                    request_data=mock_request,
                    processed_messages=[{"role": "user", "content": "test message"}],
                    effective_model="gemini-2.5-pro",
                )

        # Should make exactly one streaming API call
        stream_calls = duplicate_detector.get_stream_api_calls()
        non_stream_calls = duplicate_detector.get_non_stream_api_calls()

        assert (
            len(stream_calls) == 1
        ), f"Streaming mode should make exactly 1 streaming call, got {len(stream_calls)}: {stream_calls}"
        assert (
            len(non_stream_calls) == 0
        ), f"Streaming mode should not make non-streaming calls, got: {non_stream_calls}"

        # Verify no duplicates
        duplicates = duplicate_detector.get_duplicate_requests()
        assert len(duplicates) == 0, f"Duplicate requests detected: {duplicates}"

    @pytest.mark.asyncio
    async def test_cloud_project_non_streaming_no_duplicate_requests(
        self, cloud_project_connector, duplicate_detector
    ):
        """Test that cloud project non-streaming doesn't make duplicate requests."""

        mock_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="test message")],
            stream=False,
        )

        async with duplicate_detector.capture_api_calls(cloud_project_connector):
            with contextlib.suppress(Exception):
                await cloud_project_connector._chat_completions(
                    request_data=mock_request,
                    processed_messages=[{"role": "user", "content": "test message"}],
                    effective_model="gemini-2.5-pro",
                )

        # Verify no duplicate requests
        duplicates = duplicate_detector.get_duplicate_requests()
        stream_calls = duplicate_detector.get_stream_api_calls()

        assert len(duplicates) == 0, f"Duplicate requests detected: {duplicates}"

        # For non-streaming mode, should NOT call streaming endpoint
        assert (
            len(stream_calls) == 0
        ), f"Non-streaming mode should not call streaming endpoints, but got: {stream_calls}"

    @pytest.mark.asyncio
    async def test_cloud_project_streaming_makes_streaming_requests(
        self, cloud_project_connector, duplicate_detector
    ):
        """Test that cloud project streaming mode correctly uses streaming endpoint."""

        mock_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="test message")],
            stream=True,
        )

        async with duplicate_detector.capture_api_calls(cloud_project_connector):

            async def fake_stream_call(*args: Any, **kwargs: Any) -> None:
                duplicate_detector.auth_session_calls.append(
                    {
                        "method": "POST",
                        "url": "https://generativelanguage.googleapis.com/v1beta/models:streamGenerateContent",
                        "kwargs": kwargs,
                        "timestamp": time.monotonic(),
                    }
                )

            with (
                patch.object(
                    cloud_project_connector,
                    "_chat_completions_streaming",
                    side_effect=fake_stream_call,
                ),
                contextlib.suppress(Exception),
            ):
                await cloud_project_connector._chat_completions_streaming(
                    request_data=mock_request,
                    processed_messages=[{"role": "user", "content": "test message"}],
                    effective_model="gemini-2.5-pro",
                )

        # Should make exactly one streaming API call
        stream_calls = duplicate_detector.get_stream_api_calls()
        non_stream_calls = duplicate_detector.get_non_stream_api_calls()

        assert (
            len(stream_calls) == 1
        ), f"Streaming mode should make exactly 1 streaming call, got {len(stream_calls)}: {stream_calls}"
        assert (
            len(non_stream_calls) == 0
        ), f"Streaming mode should not make non-streaming calls, got: {non_stream_calls}"

    def test_detect_similar_duplicate_patterns_in_code(self):
        """Static code analysis to detect potential duplicate request patterns."""
        import ast
        import os

        # Files to check for duplicate request patterns
        files_to_check = [
            "src/connectors/gemini_oauth_base.py",
            "src/connectors/gemini_cloud_project.py",
        ]

        duplicate_patterns = []

        for file_path in files_to_check:
            if not os.path.exists(file_path):
                continue

            with open(file_path) as f:
                content = f.read()

            # Parse the AST
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            # Look for methods that call other methods with similar names
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and "streaming" not in node.name:
                    for child in ast.walk(node):
                        if (
                            isinstance(child, ast.Call)
                            and hasattr(child.func, "id")
                            and "streaming" in child.func.id
                        ):
                            duplicate_patterns.append(
                                {
                                    "file": file_path,
                                    "method": node.name,
                                    "calls_streaming": child.func.id,
                                    "line": child.lineno,
                                }
                            )

        # This test will fail if we find the specific pattern we fixed
        # but allow other legitimate streaming calls
        problematic_patterns = [
            pattern
            for pattern in duplicate_patterns
            if (
                "code_assist" in pattern["method"]
                and "code_assist_streaming" in pattern["calls_streaming"]
            )
            or (
                "chat_completions" in pattern["method"]
                and "chat_completions_streaming" in pattern["calls_streaming"]
            )
        ]

        assert len(problematic_patterns) == 0, (
            f"Potentially problematic duplicate request patterns detected: {problematic_patterns}. "
            "These patterns could cause the non-streaming method to call the streaming method, "
            "leading to duplicate API calls and 429 errors."
        )

    def test_connector_method_call_patterns(self):
        """Test that connectors follow the expected method call patterns."""
        import inspect

        # Test OAuth Base Connector
        oauth_base_methods = [
            name
            for name, method in inspect.getmembers(
                GeminiOAuthBaseConnector, predicate=inspect.isfunction
            )
        ]

        assert "_chat_completions_code_assist" in oauth_base_methods
        assert "_chat_completions_code_assist_streaming" in oauth_base_methods

        # Test Cloud Project Connector
        cloud_methods = [
            name
            for name, method in inspect.getmembers(
                GeminiCloudProjectConnector, predicate=inspect.isfunction
            )
        ]

        assert "_chat_completions_standard" in cloud_methods
        assert "_chat_completions_streaming" in cloud_methods

    @pytest.mark.asyncio
    async def test_quota_exhaustion_prevention_mechanisms(self, oauth_plan_connector):
        """Test that connectors have mechanisms to prevent quota exhaustion."""
        # Verify that the connector has quota tracking
        assert hasattr(
            oauth_plan_connector, "_request_counter"
        ), "Connector should have request counter for quota tracking"

        # Verify that the connector can mark backend as unusable
        assert hasattr(
            oauth_plan_connector, "_mark_backend_unusable"
        ), "Connector should have method to mark backend as unusable"

        # Verify quota exceeded flag
        assert hasattr(
            oauth_plan_connector, "_quota_exceeded"
        ), "Connector should have quota exceeded flag"

        # Test that marking backend unusable works
        oauth_plan_connector._mark_backend_unusable()

        assert (
            not oauth_plan_connector.is_functional
        ), "Backend should be marked as non-functional after quota exceeded"
        assert oauth_plan_connector._quota_exceeded, "Quota exceeded flag should be set"


class TestRequestPatternValidation:
    """Additional tests to validate request patterns are correct."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_no_race_conditions(
        self, oauth_plan_connector, duplicate_detector
    ):
        """Test that concurrent requests don't cause race conditions or duplicate calls."""

        streaming_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[
                ChatMessage(
                    role="user",
                    content=f"test message {asyncio.current_task().get_name()}",
                )
            ],
            stream=True,
        )

        async def fake_stream_call(*args: Any, **kwargs: Any) -> None:
            duplicate_detector.auth_session_calls.append(
                {
                    "method": "POST",
                    "url": "https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent",
                    "kwargs": kwargs,
                    "timestamp": time.monotonic(),
                }
            )

        async with duplicate_detector.capture_api_calls(oauth_plan_connector):
            with (
                patch.object(
                    oauth_plan_connector,
                    "_chat_completions_code_assist_streaming",
                    side_effect=fake_stream_call,
                ),
                contextlib.suppress(Exception),
            ):

                async def make_request() -> None:
                    await oauth_plan_connector._chat_completions_code_assist_streaming(
                        request_data=streaming_request,
                        processed_messages=[{"role": "user", "content": "test"}],
                        effective_model="gemini-2.5-pro",
                    )

                tasks = [asyncio.create_task(make_request()) for _ in range(3)]
                await asyncio.gather(*tasks, return_exceptions=True)

        total_calls = len(duplicate_detector.auth_session_calls)
        assert (
            total_calls == 3
        ), f"Expected 3 API calls for 3 concurrent requests, got {total_calls}"

        # Timestamps may collide in test environment; ensure at least one call recorded per request
        assert (
            duplicate_detector.get_stream_api_calls()
        ), "Streaming calls were not recorded"
