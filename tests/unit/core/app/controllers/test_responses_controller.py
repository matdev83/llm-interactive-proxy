"""Unit tests for the ResponsesController front-end logic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from src.core.app.controllers.responses_controller import ResponsesController
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatResponse,
)
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.responses_api import JsonSchema, ResponseFormat, ResponsesRequest


class StubTranslationService:
    """Translation service stub capturing usage for assertions."""

    def __init__(self) -> None:
        self.request_used = False
        self.response_used = False
        self._domain_request = SimpleNamespace(model="gpt-test", stream=False)

    def to_domain_request(self, request: object, source_format: str) -> object:
        self.request_used = True
        return self._domain_request

    def from_domain_to_responses_response(
        self, response: ChatResponse
    ) -> dict[str, object]:
        self.response_used = True
        return {
            "id": response.id,
            "object": "response",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "converted"},
                    "finish_reason": "stop",
                }
            ],
        }


class TestResponsesControllerSchemaValidation:
    """Tests covering JSON schema validation helper logic."""

    def test_validate_json_schema_allows_ref_only_properties(self) -> None:
        """Ensure properties that rely on $ref do not raise validation errors."""

        schema = {
            "type": "object",
            "properties": {
                "user": {"$ref": "#/$defs/user"},
            },
            "$defs": {
                "user": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            },
        }

        # Should not raise an exception
        ResponsesController._validate_json_schema(schema)

    def test_validate_json_schema_requires_type_or_structure(self) -> None:
        """Properties without type or structural keywords should be rejected."""

        schema = {
            "type": "object",
            "properties": {
                "invalid": {},
            },
        }

        with pytest.raises(ValueError):
            ResponsesController._validate_json_schema(schema)

    def test_validate_json_schema_supports_union_type_list(self) -> None:
        """Schema validation should accept union type declarations provided as lists."""

        schema = {
            "type": ["object", "null"],
            "properties": {
                "id": {"type": "string"},
            },
            "required": ["id"],
        }

        # Should not raise an exception when handling list-based union types
        ResponsesController._validate_json_schema(schema)

    def test_validate_json_schema_accepts_union_type_and_items_list(self) -> None:
        """Union-typed schemas with list-based items should validate successfully."""

        schema = {
            "type": ["object", "null"],
            "properties": {
                "values": {
                    "type": ["array", "null"],
                    "items": [{"type": "string"}],
                }
            },
            "additionalProperties": False,
        }

        # Should not raise a TypeError or validation error
        ResponsesController._validate_json_schema(schema)


@pytest.mark.asyncio
async def test_handle_responses_request_uses_injected_translation_service() -> None:
    """The controller should honor the DI-provided translation service."""

    translation_service = StubTranslationService()
    processor = AsyncMock()

    choice = ChatCompletionChoice(
        index=0,
        message=ChatCompletionChoiceMessage(role="assistant", content="hi"),
        finish_reason="stop",
    )
    chat_response = ChatResponse(
        id="resp-123",
        created=0,
        model="gpt-test",
        choices=[choice],
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )
    processor.process_request.return_value = ResponseEnvelope(content=chat_response)

    controller = ResponsesController(processor, translation_service=translation_service)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/responses",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "app": SimpleNamespace(state=SimpleNamespace()),
    }

    async def receive() -> dict[str, object]:  # pragma: no cover - invoked by Request
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive=receive)
    request.state.request_id = "test-request"

    schema = JsonSchema(
        name="TestSchema",
        schema={
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
        },
    )
    responses_request = ResponsesRequest(
        model="gpt-test",
        messages=[ChatMessage(role="user", content="hello")],
        response_format=ResponseFormat(json_schema=schema),
    )

    response = await controller.handle_responses_request(request, responses_request)

    assert translation_service.request_used is True
    assert translation_service.response_used is True
    assert response.status_code == 200
