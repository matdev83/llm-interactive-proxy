"""Mock implementation of DI CommandProcessor for fixture tests."""

from typing import Any

from src.core.domain.multimodal import MultimodalMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)


class MockCommandProcessorFixtures(CoreCommandProcessor):
    """Special mock implementation for fixture tests."""

    def __init__(self) -> None:
        # Skip the original __init__ to avoid any DI complexity
        self._command_handlers: dict[str, Any] = {}

    async def process_messages(
        self,
        messages: list[Any],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        """Process messages for fixture tests."""
        # Special case for test_command_parser_fixture - always return success
        if len(messages) == 1 and isinstance(messages[0], MultimodalMessage):
            # Just return success for any MultimodalMessage in this test
            # No-op for test fixture

            # Create modified messages with command removed
            modified_messages = messages.copy()
            if hasattr(messages[0], "model_copy") and callable(messages[0].model_copy):
                new_message = messages[0].model_copy()
                new_message.content = ""  # Command-only message becomes empty
                modified_messages[0] = new_message

            return ProcessedResult(
                modified_messages=modified_messages,
                command_executed=True,  # Critical for the test to pass
                command_results=["Model set to openrouter:test-model"],
            )

        # Default handling - simulate command found
        if len(messages) == 1 and isinstance(
            getattr(messages[0], "content", None), str
        ):
            content = messages[0].content
            if "!/set" in content:
                # Create modified messages with command removed
                modified_messages = messages.copy()
                if hasattr(messages[0], "model_copy") and callable(
                    messages[0].model_copy
                ):
                    new_message = messages[0].model_copy()
                    new_message.content = content.replace(
                        "!/set(model=openrouter:test-model)", ""
                    )
                    modified_messages[0] = new_message

                return ProcessedResult(
                    modified_messages=modified_messages,
                    command_executed=True,
                    command_results=["Model set to openrouter:test-model"],
                )

        # Default no-op case
        return ProcessedResult(
            modified_messages=messages, command_executed=False, command_results=[]
        )
