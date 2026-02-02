"""
Tests for ChatRequestPreparer reasoning stripping and tool output truncation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.gemini_base.chat_request_preparer import ChatRequestPreparer
from src.connectors.gemini_base.connector_context import (
    IConnectorContext,
    IMessageConverter,
    IPromptLimiter,
    IRequestBodyBuilder,
)
from src.core.config.app_config import AppConfig
from src.core.config.models.backends import BackendConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


class MockConnectorContext(IConnectorContext):
    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        backend_type: str = "gemini-oauth-auto",
    ):
        self._creds = {"access_token": "fake-token"}
        self._refresh_token_if_needed_mock = AsyncMock(return_value=True)
        self.config = config
        self.backend_type = backend_type

    @property
    def _oauth_credentials(self):
        return self._creds

    def _get_session_headers(self) -> dict[str, str]:
        return {}

    async def _discover_project_id(self, auth_session):
        return "fake-project"

    async def _refresh_token_if_needed(
        self,
        *,
        force_reload: bool = False,
        session_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> bool:
        result = await self._refresh_token_if_needed_mock(
            force_reload=force_reload,
            session_id=session_id,
            retry_after_seconds=retry_after_seconds,
        )
        return bool(result)

    async def record_rate_limit(self, *, retry_after_seconds: float | None) -> None:
        return None


class MockMessageConverter(IMessageConverter):
    def _convert_system_messages_for_code_assist(self, gemini_request):
        return gemini_request.get("contents", [])

    def _build_code_assist_request(self, gemini_request, final_contents):
        return {"contents": final_contents, "generationConfig": {}}

    def _sanitize_code_assist_tools(self, canonical_request, code_assist_request):
        pass


class MockPromptLimiter(IPromptLimiter):
    def _estimate_prompt_tokens(self, code_assist_request):
        return 0

    def _enforce_prompt_limit(self, prompt_tokens, effective_model, *, request_id=None):
        pass


class MockRequestBodyBuilder(IRequestBodyBuilder):
    def _build_code_assist_request_body(
        self, effective_model, project_id, request_data, code_assist_request
    ):
        return {"request": code_assist_request}


@pytest.mark.asyncio
async def test_prepare_strips_reasoning_content_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_STRIP_REASONING_CONTENT", raising=False)
    context = MockConnectorContext()
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": []}
    )

    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        session_id="sess-1",
        messages=[
            ChatMessage(role="user", content="hi"),
            ChatMessage(
                role="assistant",
                content="result",
                reasoning_content="internal thought",
            ),
        ],
    )

    prepared = await preparer.prepare(request_data, "gemini-2.5-pro")

    assert prepared.canonical_request.messages[1].reasoning_content is None
    passed_request = translation_service.from_domain_to_gemini_request.call_args[0][0]
    assert passed_request.messages[1].reasoning_content is None


@pytest.mark.asyncio
async def test_prepare_can_keep_reasoning_content_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_STRIP_REASONING_CONTENT", raising=False)
    config = AppConfig()
    config.backends["gemini-oauth-auto"] = BackendConfig(
        extra={"strip_reasoning_content": False}
    )

    context = MockConnectorContext(config=config)
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": []}
    )

    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        session_id="sess-2",
        messages=[
            ChatMessage(role="user", content="hi"),
            ChatMessage(
                role="assistant",
                content="result",
                reasoning_content="internal thought",
            ),
        ],
    )

    prepared = await preparer.prepare(request_data, "gemini-2.5-pro")

    assert (
        prepared.canonical_request.messages[1].reasoning_content == "internal thought"
    )


@pytest.mark.asyncio
async def test_prepare_truncates_tool_output_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_TOOL_OUTPUT_TRUNCATE_CHARS", raising=False)
    monkeypatch.delenv("GEMINI_TOOL_OUTPUT_TRUNCATE_LINES", raising=False)
    config = AppConfig()
    config.backends["gemini-oauth-auto"] = BackendConfig(
        extra={"tool_output_truncate_chars": 40}
    )

    context = MockConnectorContext(config=config)
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": []}
    )

    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    long_output = "x" * 200
    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        session_id="sess-3",
        messages=[
            ChatMessage(role="tool", content=long_output),
        ],
    )

    prepared = await preparer.prepare(request_data, "gemini-2.5-pro")

    truncated = prepared.canonical_request.messages[0].content
    assert isinstance(truncated, str)
    assert len(truncated) < len(long_output)
    assert "CONTENT TRUNCATED" in truncated


@pytest.mark.asyncio
async def test_prepare_skips_truncation_when_compaction_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_TOOL_OUTPUT_TRUNCATE_CHARS", raising=False)
    monkeypatch.delenv("GEMINI_TOOL_OUTPUT_TRUNCATE_LINES", raising=False)
    config = AppConfig()
    config.compaction.enabled = True
    config.backends["gemini-oauth-auto"] = BackendConfig(
        extra={"tool_output_truncate_chars": 40}
    )

    context = MockConnectorContext(config=config)
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": []}
    )

    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    long_output = "x" * 200
    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        session_id="sess-4",
        messages=[ChatMessage(role="tool", content=long_output)],
    )

    prepared = await preparer.prepare(request_data, "gemini-2.5-pro")

    content = prepared.canonical_request.messages[0].content
    assert isinstance(content, str)
    assert content == long_output


@pytest.mark.asyncio
async def test_prepare_uses_underscore_backend_key_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_TOOL_OUTPUT_TRUNCATE_CHARS", raising=False)
    monkeypatch.delenv("GEMINI_TOOL_OUTPUT_TRUNCATE_LINES", raising=False)
    config = AppConfig()
    config.backends["antigravity_oauth"] = BackendConfig(
        extra={"tool_output_truncate_chars": 40}
    )

    context = MockConnectorContext(config=config, backend_type="antigravity-oauth")
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": []}
    )

    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    long_output = "x" * 200
    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        session_id="sess-5",
        messages=[ChatMessage(role="tool", content=long_output)],
    )

    prepared = await preparer.prepare(request_data, "gemini-2.5-pro")

    truncated = prepared.canonical_request.messages[0].content
    assert isinstance(truncated, str)
    assert len(truncated) < len(long_output)
    assert "CONTENT TRUNCATED" in truncated
