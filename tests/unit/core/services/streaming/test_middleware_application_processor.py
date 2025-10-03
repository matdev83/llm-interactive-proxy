import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)


class MockMiddleware(IResponseMiddleware):
    def __init__(self, name: str, priority: int = 0):
        super().__init__(priority)
        self.name = name

    async def process(
        self, response: ProcessedResponse, session_id: str, context: dict
    ) -> ProcessedResponse:
        response.content = f"{response.content}[{self.name}]"
        response.metadata[self.name] = True
        return response


class OrderCheckingMiddleware(IResponseMiddleware):
    def __init__(self, name: str, priority: int = 0, order_list: list | None = None):
        super().__init__(priority)
        self.name = name
        self.order_list = order_list if order_list is not None else []

    async def process(
        self, response: ProcessedResponse, session_id: str, context: dict
    ) -> ProcessedResponse:
        self.order_list.append(self.name)
        return response


@pytest.fixture
def middleware_application_processor():
    return MiddlewareApplicationProcessor([])


@pytest.mark.asyncio
async def test_middleware_application_processor_applies_single_middleware():
    # Arrange
    mock_mw = MockMiddleware("MW1")
    processor = MiddlewareApplicationProcessor([mock_mw])
    initial_content = StreamingContent(
        content="initial", metadata={"session_id": "test_session"}
    )

    # Act
    processed_content = await processor.process(initial_content)

    # Assert
    assert processed_content.content == "initial[MW1]"
    assert processed_content.metadata.get("MW1") is True


@pytest.mark.asyncio
async def test_middleware_application_processor_applies_multiple_middleware():
    # Arrange
    mock_mw1 = MockMiddleware("MW1", priority=10)
    mock_mw2 = MockMiddleware("MW2", priority=5)
    mock_mw3 = MockMiddleware("MW3", priority=15)  # Higher priority, should run first

    # MW3 should run first, then MW1, then MW2 due to priorities
    processor = MiddlewareApplicationProcessor([mock_mw1, mock_mw2, mock_mw3])
    initial_content = StreamingContent(
        content="initial", metadata={"session_id": "test_session"}
    )

    # Act
    processed_content = await processor.process(initial_content)

    # Assert
    assert processed_content.content == "initial[MW3][MW1][MW2]"
    assert processed_content.metadata.get("MW1") is True
    assert processed_content.metadata.get("MW2") is True
    assert processed_content.metadata.get("MW3") is True


@pytest.mark.asyncio
async def test_middleware_application_processor_respects_priority_order():
    # Arrange
    order_list = []
    mw_high = OrderCheckingMiddleware("High", priority=10, order_list=order_list)
    mw_medium = OrderCheckingMiddleware("Medium", priority=5, order_list=order_list)
    mw_low = OrderCheckingMiddleware("Low", priority=1, order_list=order_list)

    processor = MiddlewareApplicationProcessor([mw_medium, mw_low, mw_high])
    initial_content = StreamingContent(
        content="start", metadata={"session_id": "test_session"}
    )

    # Act
    await processor.process(initial_content)

    # Assert
    assert order_list == ["High", "Medium", "Low"]


@pytest.mark.asyncio
async def test_middleware_application_processor_handles_empty_content():
    # Arrange
    mock_mw = MockMiddleware("MW1")
    processor = MiddlewareApplicationProcessor([mock_mw])
    initial_content = StreamingContent(
        content="", metadata={"session_id": "test_session"}
    )

    # Act
    processed_content = await processor.process(initial_content)

    # Assert
    assert processed_content.content == "[MW1]"
    assert processed_content.metadata.get("MW1") is True


@pytest.mark.asyncio
async def test_middleware_application_processor_preserves_is_done_and_is_cancellation():
    # Arrange
    mock_mw = MockMiddleware("MW1")
    processor = MiddlewareApplicationProcessor([mock_mw])

    # Test is_done
    initial_done_content = StreamingContent(
        content="done", is_done=True, metadata={"session_id": "test_session"}
    )
    processed_done_content = await processor.process(initial_done_content)
    assert processed_done_content.is_done is True
    assert processed_done_content.is_cancellation is False

    # Test is_cancellation
    initial_cancellation_content = StreamingContent(
        content="cancel", is_cancellation=True, metadata={"session_id": "test_session"}
    )
    processed_cancellation_content = await processor.process(
        initial_cancellation_content
    )
    assert (
        processed_cancellation_content.is_done is False
    )  # Middleware doesn't change is_done
    assert processed_cancellation_content.is_cancellation is True


@pytest.mark.asyncio
async def test_middleware_application_processor_metadata_and_usage_pass_through():
    # Arrange
    mock_mw = MockMiddleware("MW1")
    processor = MiddlewareApplicationProcessor([mock_mw])

    initial_metadata = {"original": True, "session_id": "test_session"}
    initial_usage = {"tokens": 10}
    initial_raw_data = {"raw": "data"}

    initial_content = StreamingContent(
        content="data",
        metadata=initial_metadata,
        usage=initial_usage,
        raw_data=initial_raw_data,
    )

    # Act
    processed_content = await processor.process(initial_content)

    # Assert
    assert processed_content.metadata.get("original") is True
    assert processed_content.metadata.get("MW1") is True
    assert processed_content.usage == initial_usage
    assert processed_content.raw_data == initial_raw_data
