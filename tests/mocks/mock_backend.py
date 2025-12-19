from typing import Any

from src.connectors.base import LLMBackend
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope

from tests.unit.openai_connector_tests.test_streaming_response import AsyncIterBytes


class MockBackend(LLMBackend):
    def __init__(self, response_chunks: list[bytes]):
        self.response_chunks = response_chunks
        super().__init__()

    async def chat_completions_stream(
        self,
        request_data: dict,
        session_id: str | None = None,
        **kwargs,
    ) -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(
            content=AsyncIterBytes(self.response_chunks),
            headers={},
        )

    def get_available_models(self) -> list[str]:
        return ["test-model"]

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list,
        effective_model: str,
        identity: Any = None,
        **kwargs,
    ) -> "ResponseEnvelope":
        raise NotImplementedError

    async def initialize(self, **kwargs) -> None:
        pass
