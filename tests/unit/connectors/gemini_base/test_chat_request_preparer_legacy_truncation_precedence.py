from __future__ import annotations

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
from src.core.services.legacy_compression_compatibility_resolver import (
    ConnectorTruncationCompatibilityDecision,
    ConnectorTruncationCompatibilityDiagnostics,
    DynamicCompressionCompatibilityDiagnostics,
    PytestCompatibilityDecision,
)


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


class ForcedTruncationResolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, int | bool | None]] = []

    def resolve_pytest_mode(
        self,
        *,
        legacy_pytest_enabled: bool,
        dynamic_pytest_mode: bool | str | None,
    ) -> PytestCompatibilityDecision:
        return PytestCompatibilityDecision(
            effective_enabled=legacy_pytest_enabled,
            source="legacy",
        )

    def resolve_pytest_mode_with_diagnostics(
        self,
        *,
        legacy_pytest_enabled: bool,
        dynamic_pytest_mode: bool | str | None,
    ) -> tuple[PytestCompatibilityDecision, DynamicCompressionCompatibilityDiagnostics]:
        return (
            self.resolve_pytest_mode(
                legacy_pytest_enabled=legacy_pytest_enabled,
                dynamic_pytest_mode=dynamic_pytest_mode,
            ),
            DynamicCompressionCompatibilityDiagnostics(),
        )

    def resolve_connector_truncation(
        self,
        *,
        connector_max_chars: int | None,
        connector_max_lines: int | None,
        compaction_enabled: bool,
        dynamic_compression_enabled: bool,
    ) -> ConnectorTruncationCompatibilityDecision:
        self.calls.append(
            {
                "connector_max_chars": connector_max_chars,
                "connector_max_lines": connector_max_lines,
                "compaction_enabled": compaction_enabled,
                "dynamic_compression_enabled": dynamic_compression_enabled,
            }
        )
        return ConnectorTruncationCompatibilityDecision(
            effective_max_chars=40,
            effective_max_lines=None,
            source="forced",
        )

    def resolve_connector_truncation_with_diagnostics(
        self,
        *,
        connector_max_chars: int | None,
        connector_max_lines: int | None,
        compaction_enabled: bool,
        dynamic_compression_enabled: bool,
    ) -> tuple[
        ConnectorTruncationCompatibilityDecision,
        ConnectorTruncationCompatibilityDiagnostics,
    ]:
        return (
            self.resolve_connector_truncation(
                connector_max_chars=connector_max_chars,
                connector_max_lines=connector_max_lines,
                compaction_enabled=compaction_enabled,
                dynamic_compression_enabled=dynamic_compression_enabled,
            ),
            ConnectorTruncationCompatibilityDiagnostics(applied=["forced"]),
        )


class RaisingResolver(ForcedTruncationResolver):
    def resolve_connector_truncation_with_diagnostics(
        self,
        *,
        connector_max_chars: int | None,
        connector_max_lines: int | None,
        compaction_enabled: bool,
        dynamic_compression_enabled: bool,
    ) -> tuple[
        ConnectorTruncationCompatibilityDecision,
        ConnectorTruncationCompatibilityDiagnostics,
    ]:
        raise RuntimeError("resolver failure")


@pytest.mark.asyncio
async def test_prepare_uses_legacy_resolver_for_truncation_precedence() -> None:
    config = AppConfig()
    config.compaction.enabled = True
    config.backends["gemini-oauth-auto"] = BackendConfig(
        extra={"tool_output_truncate_chars": 300}
    )
    context = MockConnectorContext(config=config)
    resolver = ForcedTruncationResolver()

    translation_service = MagicMock()
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": []}
    )
    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=MockMessageConverter(),
        prompt_limiter=MockPromptLimiter(),
        request_body_builder=MockRequestBodyBuilder(),
        translation_service=translation_service,
        legacy_compression_compatibility_resolver=resolver,
    )

    original_tool_output = "x" * 200
    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        session_id="sess-resolver-path",
        messages=[ChatMessage(role="tool", content=original_tool_output)],
    )

    prepared = await preparer.prepare(request_data, "gemini-2.5-pro")

    assert resolver.calls
    assert resolver.calls[0]["compaction_enabled"] is True
    assert resolver.calls[0]["dynamic_compression_enabled"] is False
    assert resolver.calls[0]["connector_max_chars"] == 300
    content = prepared.canonical_request.messages[0].content
    assert isinstance(content, str)
    assert content != original_tool_output
    assert "CONTENT TRUNCATED" in content


@pytest.mark.asyncio
async def test_prepare_fails_open_when_legacy_truncation_resolver_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = AppConfig()
    config.backends["gemini-oauth-auto"] = BackendConfig(
        extra={"tool_output_truncate_chars": 80}
    )
    context = MockConnectorContext(config=config)
    translation_service = MagicMock()
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": []}
    )
    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=MockMessageConverter(),
        prompt_limiter=MockPromptLimiter(),
        request_body_builder=MockRequestBodyBuilder(),
        translation_service=translation_service,
        legacy_compression_compatibility_resolver=RaisingResolver(),
    )

    original_tool_output = "x" * 200
    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        session_id="sess-resolver-fail-open",
        messages=[ChatMessage(role="tool", content=original_tool_output)],
    )

    prepared = await preparer.prepare(request_data, "gemini-2.5-pro")

    content = prepared.canonical_request.messages[0].content
    assert isinstance(content, str)
    assert content == original_tool_output
    assert any(
        "compatibility resolution failed open" in record.message.lower()
        for record in caplog.records
    )
