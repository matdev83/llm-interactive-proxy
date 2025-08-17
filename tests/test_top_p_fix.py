from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.response_processor import IResponseProcessor
from src.core.interfaces.session_service import ISessionService
from src.core.services.request_processor import RequestProcessor


def test_top_p_fix_with_actual_request():
    """Test that demonstrates our fix works with a real request that includes top_p."""

    # Create a mock session with minimal required attributes
    class MockSession:
        def __init__(self):
            self.session_id = "test-session"
            self.state = MockState()

    class MockState:
        def __init__(self):
            self.backend_config = MockBackendConfig()
            self.reasoning_config = MockReasoningConfig()
            self.project = None

    class MockBackendConfig:
        def __init__(self):
            self.backend_type = "anthropic"
            self.model = "anthropic:claude-3-haiku-20240229"

    class MockReasoningConfig:
        def __init__(self):
            self.temperature = None

    # This is a request that would have triggered the original error
    # It includes top_p which would have been added to extra_body before our fix
    request_data = {
        "model": "anthropic:claude-3-haiku-20240229",
        "max_tokens": 128,
        "top_p": 0.9,  # This would have caused the error before our fix
        "messages": [{"role": "user", "content": "Hello"}],
    }

    messages = [{"role": "user", "content": "Hello"}]
    session = MockSession()

    # Create a RequestProcessor (we won't actually use its methods)
    class MockCommandService(ICommandService):
        async def process_command(
            self, command_name: str, args: dict[str, Any], session: Any
        ) -> CommandResult:
            raise NotImplementedError

        async def process_text_for_commands(
            self, text: str, session: Any
        ) -> tuple[str, bool]:
            raise NotImplementedError

        async def process_messages_for_commands(
            self, messages: list[Any], session: Any
        ) -> tuple[list[Any], bool]:
            raise NotImplementedError

        async def process_commands(
            self, messages: list[Any], session_id: str
        ) -> ProcessedResult:
            raise NotImplementedError

        async def register_command(
            self, command_name: str, command_handler: Any
        ) -> None:
            raise NotImplementedError

    class MockBackendService(IBackendService):
        async def call_completion(self, request: Any, stream: bool = False) -> Any:
            raise NotImplementedError

        async def validate_backend_and_model(
            self, backend: str, model: str
        ) -> tuple[bool, str | None]:
            raise NotImplementedError

        async def chat_completions(self, request: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    class MockSessionService(ISessionService):
        async def get_session(self, session_id: str) -> Any:
            raise NotImplementedError

        async def create_session(self, session_id: str) -> Any:
            raise NotImplementedError

        async def update_session(self, session: Any) -> None:
            raise NotImplementedError

        async def delete_session(self, session_id: str) -> bool:
            raise NotImplementedError

        async def get_all_sessions(self) -> list[Any]:
            raise NotImplementedError

    class MockResponseProcessor(IResponseProcessor):
        async def process_response(self, response: Any, session: Any) -> Any:
            raise NotImplementedError

        def _extract_response_content(self, response: Any) -> Any:
            raise NotImplementedError

        def process_streaming_response(
            self, response_iter: Any, session_id: str
        ) -> Any:
            raise NotImplementedError

        async def register_middleware(
            self, middleware: Any, _priority: int = 0
        ) -> None:
            raise NotImplementedError

    processor = RequestProcessor(
        command_service=MockCommandService(),
        backend_service=MockBackendService(),
        session_service=MockSessionService(),
        response_processor=MockResponseProcessor(),
    )

    # This would have failed before our fix with:
    # "TypeError: src.models.ChatCompletionRequest() got multiple values for keyword argument 'top_p'"
    # But now it should work correctly
    chat_request = processor._convert_to_domain_request(request_data, messages, session)

    # Verify that top_p is in the main ChatRequest fields
    assert chat_request.top_p == 0.9

    # Most importantly, verify that top_p is NOT in extra_body
    # This is the key fix that prevents the duplicate keyword argument error
    assert "top_p" not in (chat_request.extra_body or {})

    # Verify other parameters are correctly handled
    assert chat_request.model == "anthropic:claude-3-haiku-20240229"
    assert chat_request.max_tokens == 128
