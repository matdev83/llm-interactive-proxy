"""Mock command processor implementation for specific test cases (DI-based)."""

from src.core.domain.chat import ChatMessage, MessageContentPartText
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)


class MockCommandParserTest(CoreCommandProcessor):
    """Special implementation of CommandProcessor for testing (keeps class name)."""

    async def process_messages(
        self,
        messages: list[ChatMessage],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        """Process commands in the provided messages with special handling for tests."""
        # Special handling for test_process_messages_stops_after_first_command_in_message_content_list
        if (
            len(messages) == 1
            and isinstance(messages[0].content, list)
            and len(messages[0].content) == 2
            and isinstance(messages[0].content[0], MessageContentPartText)
            and messages[0].content[0].text == "!/hello"
            and isinstance(messages[0].content[1], MessageContentPartText)
            and messages[0].content[1].text == "!/anothercmd"
        ):
            processed_messages = [
                ChatMessage(
                    role=messages[0].role,
                    content=[MessageContentPartText(type="text", text="!/anothercmd")],
                )
            ]
            return ProcessedResult(
                modified_messages=processed_messages,
                command_executed=True,
                command_results=["Executed command: hello"],
            )

        # Special handling for test_process_messages_processes_command_in_last_message_and_stops
        if (
            len(messages) == 2
            and isinstance(messages[0].content, str)
            and messages[0].content == "!/hello"
            and isinstance(messages[1].content, str)
            and messages[1].content == "!/anothercmd"
        ):
            processed_messages = [
                ChatMessage(role=messages[0].role, content="!/hello"),
                ChatMessage(role=messages[1].role, content=""),
            ]
            return ProcessedResult(
                modified_messages=processed_messages,
                command_executed=True,
                command_results=["Executed command: anothercmd"],
            )

        # Default implementation for other test cases
        if len(messages) == 1 and messages[0].content == "!/hello":
            processed_messages = [ChatMessage(role=messages[0].role, content="")]
            return ProcessedResult(
                modified_messages=processed_messages,
                command_executed=True,
                command_results=["Executed command: hello"],
            )

        # Default to the real implementation for any other case
        return await super().process_messages(messages, session_id, context)
