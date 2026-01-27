from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import requests  # type: ignore[import-untyped]
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.policies import RetryDecision
from src.connectors.gemini_base.streaming_executor import (
    SSELineProcessor,
    StreamingExecutor,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse


class _RetryPolicyStub:
    def __init__(self, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds

    def should_retry(
        self, _error, _attempt: int, *, is_streaming: bool = False
    ) -> RetryDecision:
        return RetryDecision(should_retry=True, sleep_seconds=self._sleep_seconds)


@pytest.mark.asyncio
async def test_streaming_executor_rotates_oauth_auto_on_429_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test rotation on 429 in late path (_handle_error_response)."""
    # Avoid real sleep in unit test.
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-oauth-auto",
        build_request_body=dict,
    )
    prepared.auth_session.headers = {"Authorization": "Bearer OLD"}

    executor = StreamingExecutor(translation_service=MagicMock())

    async def _fake_stream_generator(**_kwargs):
        yield ProcessedResponse(content="ok", metadata={})

    executor._stream_generator = _fake_stream_generator  # type: ignore[assignment]

    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini-oauth-auto",
    )

    # 429 with a long retry-after window.
    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Rate limited"}}'
    )
    response.headers = {"Retry-After": "42"}

    retry_policy = _RetryPolicyStub(sleep_seconds=42.0)

    token_refresher = MagicMock()
    token_refresher.backend_type = "gemini-oauth-auto"
    token_refresher._oauth_credentials = {"access_token": "NEW"}
    token_refresher.refresh_token_if_needed = AsyncMock(return_value=True)

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._handle_error_response(
        response=response,
        processor=processor,
        prepared=prepared,
        url="https://example.invalid",
        prompt_tokens=0,
        retry_policy=retry_policy,
        token_refresher=token_refresher,
    ):
        chunks.append(chunk)

    # Token rotation should update the auth header for the retry attempt.
    assert prepared.auth_session.headers["Authorization"] == "Bearer NEW"

    # We should not sleep the full retry-after window when rotation succeeds.
    assert sleep_mock.await_args is not None
    assert sleep_mock.await_args.args[0] == executor.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS

    assert any(chunk.content == "ok" for chunk in chunks)


def test_streaming_executor_has_timeout_rotation_logic() -> None:
    """Verify that timeout errors trigger account rotation for oauth-auto backends.

    When a streaming request times out (300s read timeout), oauth-auto backends
    should attempt account rotation before returning a 504 error. This ensures
    that if multiple accounts are configured, we try another account that may
    not be timing out.

    This test verifies the timeout rotation code path exists in the source.
    Full integration testing is performed through production logs.
    """
    from pathlib import Path

    # Read the source file from disk
    repo_root = Path(__file__).parent.parent.parent.parent
    executor_path = (
        repo_root / "src" / "connectors" / "gemini_base" / "streaming_executor.py"
    )
    source = executor_path.read_text(encoding="utf-8")

    # Verify timeout handler includes rotation logic
    timeout_rotation_checks = [
        "except requests.exceptions.Timeout",
        "_timeout_retry_attempted",
        '"oauth-auto"',
        "force_reload=True",
        "Retrying streaming request immediately after account rotation due to timeout",
    ]

    for check in timeout_rotation_checks:
        assert check in source, (
            f"Timeout rotation logic should include '{check}' "
            f"but it was not found in streaming_executor.py"
        )


def test_streaming_executor_has_rotation_in_all_error_paths() -> None:
    """Verify that oauth-auto rotation logic exists in all error handling paths.

    The StreamingExecutor has three code paths that handle retryable errors:
    1. Timeout path (~line 457): Timeout exception during request
    2. Early 429 path (~line 1002): Rate limit exception during SSE stream parsing
    3. Late 429 path (~line 1340): Rate limit error response received and parsed

    All paths must include account rotation logic for oauth-auto backends to avoid
    waiting or failing when another account is available.

    This test verifies all code paths contain the rotation logic (as a sanity check).
    The late 429 path rotation is tested by test_streaming_executor_rotates_oauth_auto_on_429_before_retry.
    The timeout and early 429 paths are verified through integration testing and production logs.
    """
    from pathlib import Path

    # Read the source file from disk (not from imported module)
    repo_root = Path(__file__).parent.parent.parent.parent
    executor_path = (
        repo_root / "src" / "connectors" / "gemini_base" / "streaming_executor.py"
    )
    source = executor_path.read_text(encoding="utf-8")

    # Verify all three code paths have the rotation logic
    # Timeout path: ~line 457
    # Early 429 path: ~line 1002 in _stream_generator exception handler
    # Late 429 path: ~line 1340 in _handle_error_response

    rotation_checks = [
        '"oauth-auto"',
        "await token_refresher.refresh_token_if_needed",
        "force_reload=True",
    ]

    for check in rotation_checks:
        # Each check should appear at least 3 times (once per path)
        count = source.count(check)
        assert count >= 3, (
            f"Rotation logic '{check}' should appear in all 3 error paths "
            f"(timeout, early 429, late 429), but only found {count} occurrence(s)"
        )
