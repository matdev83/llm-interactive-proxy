"""
Regression test for Windows double-ampersand fixer client_os propagation.

This test verifies that client_os is correctly propagated through the streaming
pipeline to the ToolCallReactorFeature, enabling the WindowsDoubleAmpersandFixer
to replace && with ; in Execute tool calls for Windows clients.

Bug Description:
- RequestProcessorService correctly detects client_os and stores it in
  context.processing_context.values["client_os"]
- However, the streaming pipeline did NOT propagate this value to the
  MiddlewareApplicationProcessor context dict
- As a result, ToolCallReactorFeature received client_os=None and skipped
  the && replacement, causing PowerShell errors on Windows

Fix:
- BackendRequestManager._attach_stream_context() now extracts client_os from
  context.processing_context.values and injects it into chunk metadata
- MiddlewareApplicationProcessor.process() now extracts client_os from
  content.metadata and adds it to the context dict
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)


class TestClientOsPropagationToMiddleware:
    """Regression tests for client_os propagation through streaming pipeline."""

    @pytest.mark.asyncio
    async def test_client_os_propagated_from_metadata_to_context(self) -> None:
        """Verify client_os in metadata is extracted and added to middleware context.

        This is the core regression test. If MiddlewareApplicationProcessor stops
        extracting client_os from metadata, the WindowsDoubleAmpersandFixer will
        receive client_os=None and fail to fix && commands on Windows.
        """
        captured_context: dict[str, Any] = {}

        class ContextCapturingMiddleware:
            priority = 0

            async def process(
                self,
                response: ProcessedResponse,
                session_id: str,
                context: dict[str, Any],
                is_streaming: bool = False,
            ) -> ProcessedResponse:
                captured_context.update(context)
                return response

        processor = MiddlewareApplicationProcessor([ContextCapturingMiddleware()])

        content = StreamingContent(
            content="test",
            metadata={
                "session_id": "test-session",
                "client_os": "windows",
            },
        )

        await processor.process(content)

        assert "client_os" in captured_context, (
            "client_os must be propagated from metadata to context. "
            "Without this, WindowsDoubleAmpersandFixer cannot detect Windows clients."
        )
        assert captured_context["client_os"] == "windows"

    @pytest.mark.asyncio
    async def test_client_os_not_added_when_missing_from_metadata(self) -> None:
        """Verify client_os is not added if not present in metadata."""
        captured_context: dict[str, Any] = {}

        class ContextCapturingMiddleware:
            priority = 0

            async def process(
                self,
                response: ProcessedResponse,
                session_id: str,
                context: dict[str, Any],
                is_streaming: bool = False,
            ) -> ProcessedResponse:
                captured_context.update(context)
                return response

        processor = MiddlewareApplicationProcessor([ContextCapturingMiddleware()])

        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-session"},
        )

        await processor.process(content)

        assert "client_os" not in captured_context

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "os_value",
        ["windows", "linux", "macos", "darwin", "win32 10.0.19045"],
    )
    async def test_various_client_os_values_propagated(self, os_value: str) -> None:
        """Verify different client_os values are correctly propagated."""
        captured_context: dict[str, Any] = {}

        class ContextCapturingMiddleware:
            priority = 0

            async def process(
                self,
                response: ProcessedResponse,
                session_id: str,
                context: dict[str, Any],
                is_streaming: bool = False,
            ) -> ProcessedResponse:
                captured_context.update(context)
                return response

        processor = MiddlewareApplicationProcessor([ContextCapturingMiddleware()])

        content = StreamingContent(
            content="test",
            metadata={
                "session_id": "test-session",
                "client_os": os_value,
            },
        )

        await processor.process(content)

        assert (
            captured_context.get("client_os") == os_value
        ), f"client_os '{os_value}' must be propagated unchanged"


class TestProcessingContextClientOsExtraction:
    """Tests for extracting client_os from ProcessingContext in streaming pipeline."""

    def test_processing_context_values_accessible(self) -> None:
        """Verify ProcessingContext.values can store and retrieve client_os."""
        processing_context = ProcessingContext()
        processing_context.update({"client_os": "windows"})

        assert processing_context.values.get("client_os") == "windows"

    def test_request_context_processing_context_integration(self) -> None:
        """Verify RequestContext can hold ProcessingContext with client_os."""
        processing_context = ProcessingContext()
        processing_context.update({"client_os": "windows"})

        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=processing_context,
        )

        assert context.processing_context is not None
        assert context.processing_context.values.get("client_os") == "windows"


class TestEndToEndClientOsFlow:
    """End-to-end tests simulating the full client_os propagation flow."""

    @pytest.mark.asyncio
    async def test_windows_client_os_enables_ampersand_fix_detection(self) -> None:
        """Simulate the full flow: metadata -> context -> fixer eligibility check.

        This test verifies that a Windows client_os in metadata results in a
        context where WindowsDoubleAmpersandFixer.should_process returns True.
        """
        from src.core.services.windows_double_ampersand_fixer import (
            WindowsDoubleAmpersandFixer,
        )

        captured_context: dict[str, Any] = {}

        class ContextCapturingMiddleware:
            priority = 0

            async def process(
                self,
                response: ProcessedResponse,
                session_id: str,
                context: dict[str, Any],
                is_streaming: bool = False,
            ) -> ProcessedResponse:
                captured_context.update(context)
                return response

        processor = MiddlewareApplicationProcessor([ContextCapturingMiddleware()])

        content = StreamingContent(
            content="test",
            metadata={
                "session_id": "test-session",
                "client_os": "windows",
            },
        )

        await processor.process(content)

        fixer = WindowsDoubleAmpersandFixer(enabled=True)
        client_os = captured_context.get("client_os")

        assert fixer.should_process("Execute", client_os) is True, (
            "With client_os='windows' in context, fixer should process Execute tool. "
            "If this fails, the && -> ; replacement will not happen for Windows clients."
        )

    @pytest.mark.asyncio
    async def test_non_windows_client_os_skips_ampersand_fix(self) -> None:
        """Verify non-Windows clients do not trigger ampersand fixing."""
        from src.core.services.windows_double_ampersand_fixer import (
            WindowsDoubleAmpersandFixer,
        )

        captured_context: dict[str, Any] = {}

        class ContextCapturingMiddleware:
            priority = 0

            async def process(
                self,
                response: ProcessedResponse,
                session_id: str,
                context: dict[str, Any],
                is_streaming: bool = False,
            ) -> ProcessedResponse:
                captured_context.update(context)
                return response

        processor = MiddlewareApplicationProcessor([ContextCapturingMiddleware()])

        content = StreamingContent(
            content="test",
            metadata={
                "session_id": "test-session",
                "client_os": "linux",
            },
        )

        await processor.process(content)

        fixer = WindowsDoubleAmpersandFixer(enabled=True)
        client_os = captured_context.get("client_os")

        assert fixer.should_process("Execute", client_os) is False

    @pytest.mark.asyncio
    async def test_missing_client_os_skips_ampersand_fix(self) -> None:
        """Verify missing client_os does not trigger ampersand fixing.

        This is the bug scenario: if client_os is not propagated,
        should_process returns False and Windows users see PowerShell errors.
        """
        from src.core.services.windows_double_ampersand_fixer import (
            WindowsDoubleAmpersandFixer,
        )

        captured_context: dict[str, Any] = {}

        class ContextCapturingMiddleware:
            priority = 0

            async def process(
                self,
                response: ProcessedResponse,
                session_id: str,
                context: dict[str, Any],
                is_streaming: bool = False,
            ) -> ProcessedResponse:
                captured_context.update(context)
                return response

        processor = MiddlewareApplicationProcessor([ContextCapturingMiddleware()])

        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-session"},
        )

        await processor.process(content)

        fixer = WindowsDoubleAmpersandFixer(enabled=True)
        client_os = captured_context.get("client_os")

        assert client_os is None
        assert fixer.should_process("Execute", client_os) is False
