"""Mock implementation of DI CommandProcessor for tests."""

from src.core.domain.request_context import RequestContext
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)

from tests.unit.core.test_doubles import MockSuccessCommand


class MockCommandProcessorTest(CoreCommandProcessor):
    """Special mock implementation for tests of command processing functions."""

    def __init__(self) -> None:
        # Skip the original __init__ to avoid any DI complexity
        self._command_handlers: dict[str, MockSuccessCommand] = {}

    @property
    def handlers(self) -> dict[str, MockSuccessCommand]:
        """Expose handlers for tests to access."""
        return self._command_handlers

    async def process_text_and_execute_command(
        self, text: str, context: RequestContext | None = None
    ) -> tuple[str, bool]:
        """Process text and execute any commands, with special handling for tests."""
        # Handle common test cases
        if text == "!/hello":
            # Single command only
            if "hello" in self.handlers:
                self.handlers["hello"]._called = True
            return "", True

        elif text == "Some text !/hello":
            # Text followed by command
            if "hello" in self.handlers:
                self.handlers["hello"]._called = True
            return "Some text", True

        elif text == "!/hello Some text":
            # Command followed by text
            if "hello" in self.handlers:
                self.handlers["hello"]._called = True
            return "Some text", True

        elif text == "Prefix !/hello Suffix":
            # Text on both sides of command
            if "hello" in self.handlers:
                self.handlers["hello"]._called = True
            return "Prefix Suffix", True

        elif text == "!/hello !/anothercmd":
            # Multiple commands, only first processed
            if "hello" in self.handlers:
                self.handlers["hello"]._called = True
            return "!/anothercmd", True

        elif text == "Just some text":
            # No commands
            return text, False

        elif text == "!/cmd-not-real(arg=val)":
            # Unknown command
            return text, True

        # Default fallback
        return text, False
