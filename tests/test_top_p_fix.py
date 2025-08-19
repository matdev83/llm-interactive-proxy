from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.request_processor_service import RequestProcessor


def test_top_p_fix_with_actual_request() -> None:
    """Test that demonstrates our fix works with a real request that includes top_p."""

    # Create a mock session with minimal required attributes
    class MockSession:
        def __init__(self) -> None:
            self.session_id = "test-session"
            self.state = MockState()

    class MockState:
        def __init__(self) -> None:
            self.backend_config = MockBackendConfig()
            self.reasoning_config = MockReasoningConfig()
            self.project: Any = None

    class MockBackendConfig:
        def __init__(self) -> None:
            self.backend_type: str = "anthropic"
            self.model: str = "anthropic:claude-3-haiku-20240229"

    class MockReasoningConfig:
        def __init__(self) -> None:
            self.temperature: Any = None

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
    from unittest.mock import MagicMock, AsyncMock

    processor = RequestProcessor(
        command_service=MagicMock(spec=ICommandService),
        backend_service=MagicMock(spec=IBackendService),
        session_service=MagicMock(spec=ISessionService),
        response_processor=MagicMock(spec=IResponseProcessor),
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
