"""Unit tests for the ResponsesController front-end logic."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from src.core.app.controllers.responses_controller import ResponsesController
from src.core.common.exceptions import ResponsesProviderLimitationError
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatResponse,
)
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.responses_api import (
    MAX_SCHEMA_COLLECTION_ITEMS,
    MAX_SCHEMA_DEPTH,
    JsonSchema,
    ResponseFormat,
    ResponsesRequest,
)
from src.core.domain.responses_native_wiring import (
    RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY,
)
from src.core.domain.usage_summary import UsageSummary

from tests.utils.responses_controller_test_deps import (
    build_responses_controller_backend_kwargs,
)


class StubTranslationService:
    """Translation service stub capturing usage for assertions."""

    def __init__(self) -> None:
        self.request_used = False
        self.response_used = False
        self._domain_request = CanonicalChatRequest(
            model="gpt-test",
            messages=[ChatMessage(role="user", content="stub")],
            stream=False,
        )

    def to_domain_request(
        self, request: object, source_format: str
    ) -> CanonicalChatRequest:
        self.request_used = True
        return self._domain_request

    def from_domain_request(
        self, request: CanonicalChatRequest, target_format: str
    ) -> dict[str, object]:
        return {"model": request.model, "target_format": target_format}

    def to_domain_response(self, response: object, source_format: str) -> object:
        return response

    def from_domain_response(
        self, response: ChatResponse, target_format: str = "openai"
    ) -> dict[str, object]:
        self.response_used = True
        return {
            "id": response.id,
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "converted"},
                    "finish_reason": "stop",
                }
            ],
        }

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


def _make_request() -> Request:
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
    return request


def _responses_request(**kwargs: object) -> ResponsesRequest:
    payload: dict[str, object] = {"model": "gpt-test"}
    payload.update(kwargs)
    return ResponsesRequest.model_validate(payload)


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

    def test_validate_json_schema_allows_required_from_composed_schema(self) -> None:
        """Required fields supplied via composition keywords should be accepted."""

        schema = {
            "type": "object",
            "properties": {
                "metadata": {"type": "object"},
            },
            "allOf": [
                {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                    },
                }
            ],
            "required": ["slug"],
        }

        # Should not raise since slug is introduced via allOf composition
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

    def test_validate_json_schema_rejects_excessive_depth(self) -> None:
        """Schemas that exceed the supported nesting depth should be rejected."""

        schema: dict[str, object] = {"type": "object", "properties": {}}
        cursor = cast(dict[str, object], schema["properties"])
        for level in range(MAX_SCHEMA_DEPTH + 1):
            next_layer: dict[str, object] = {"type": "object", "properties": {}}
            cursor[f"layer_{level}"] = next_layer
            cursor = cast(dict[str, object], next_layer["properties"])

        with pytest.raises(ValueError, match="maximum allowed depth"):
            ResponsesController._validate_json_schema(schema)  # type: ignore[arg-type]

    def test_validate_json_schema_rejects_excessive_width(self) -> None:
        """Schemas with too many peer keys should be rejected early."""

        properties: dict[str, object] = {}
        schema = {"type": "object", "properties": properties}
        for index in range(MAX_SCHEMA_COLLECTION_ITEMS + 1):
            properties[f"field_{index}"] = {"type": "string"}

        with pytest.raises(ValueError, match="cannot contain more than"):
            ResponsesController._validate_json_schema(schema)

    def test_validate_json_schema_rejects_overlong_regex_patterns(self) -> None:
        """Regex patterns that are excessively long should be rejected."""

        long_pattern = "^" + "a" * 600 + "$"
        schema = {
            "type": "object",
            "properties": {
                "code": {"type": "string", "pattern": long_pattern},
            },
        }

        with pytest.raises(ValueError) as exc:
            ResponsesController._validate_json_schema(schema)

        assert "Regex pattern too long" in str(exc.value)

    def test_validate_json_schema_rejects_nested_unbounded_regex(self) -> None:
        """Schemas with nested unbounded regex quantifiers must be rejected to avoid ReDoS."""

        schema = {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "pattern": r"^(?:a+)+$",
                }
            },
        }

        with pytest.raises(ValueError) as exc:
            ResponsesController._validate_json_schema(schema)

        assert "nested unbounded quantifiers" in str(exc.value)

    def test_validate_json_schema_accepts_safe_nested_quantifiers(self) -> None:
        """Quantifiers that do not repeat unbounded groups should be allowed."""

        schema = {
            "type": "object",
            "properties": {
                "sequence": {
                    "type": "string",
                    "pattern": r"^(?:ab?)+$",
                }
            },
        }

        ResponsesController._validate_json_schema(schema)


@pytest.mark.asyncio
async def test_handle_responses_request_uses_injected_translation_service() -> None:
    """The controller should use the DI translation service for response conversion."""

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
        usage=UsageSummary(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    processor.process_request.return_value = ResponseEnvelope(
        content=cast(Any, chat_response)
    )

    controller = ResponsesController(
        processor,
        translation_service=translation_service,
        **build_responses_controller_backend_kwargs(),
    )

    request = _make_request()

    schema = JsonSchema(
        name="TestSchema",
        description=None,
        schema={
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
        },
        strict=True,
    )
    responses_request = _responses_request(
        messages=[ChatMessage(role="user", content="hello")],
        response_format=ResponseFormat(type="json_schema", json_schema=schema),
    )

    response = await controller.handle_responses_request(request, responses_request)

    assert translation_service.request_used is False
    assert translation_service.response_used is True
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_handle_responses_request_stores_legacy_choices_payload_for_chaining() -> (
    None
):
    """Legacy `choices` payloads must still populate the session store for later turns."""

    translation_service = StubTranslationService()
    processor = AsyncMock()
    processor.process_request.return_value = ResponseEnvelope(
        content={
            "id": "resp-legacy",
            "object": "response",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "legacy assistant reply",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    )

    kwargs = build_responses_controller_backend_kwargs()
    controller = ResponsesController(
        processor,
        translation_service=translation_service,
        **kwargs,
    )

    await controller.handle_responses_request(
        _make_request(),
        _responses_request(input="hello"),
    )

    resolved = await kwargs["responses_session_store"].resolve("resp-legacy")
    assert resolved is not None
    assert len(resolved.output_items) == 1
    assert resolved.output_items[0].type == "message"
    assert resolved.output_items[0].role == "assistant"
    assert resolved.output_items[0].content is not None
    assert resolved.output_items[0].content[0].type == "output_text"
    assert resolved.output_items[0].content[0].text == "legacy assistant reply"


@pytest.mark.asyncio
async def test_previous_response_id_chain_reuses_stored_legacy_choices_output() -> None:
    """Chained turns must project prior assistant text even when the first turn used `choices`."""

    translation_service = StubTranslationService()
    processor = AsyncMock()
    processor.process_request.side_effect = [
        ResponseEnvelope(
            content={
                "id": "resp-legacy",
                "object": "response",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "legacy assistant reply",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        ),
        ResponseEnvelope(
            content={
                "id": "resp-followup",
                "object": "response",
                "output": [],
            }
        ),
    ]

    kwargs = build_responses_controller_backend_kwargs()
    kwargs["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="anthropic", model="claude-3-5-sonnet", uri_params={}
        )
    )
    controller = ResponsesController(
        processor,
        translation_service=translation_service,
        **kwargs,
    )

    await controller.handle_responses_request(
        _make_request(),
        _responses_request(model="anthropic:claude-3-5-sonnet", input="hello"),
    )
    await controller.handle_responses_request(
        _make_request(),
        _responses_request(
            model="anthropic:claude-3-5-sonnet",
            input="what next?",
            previous_response_id="resp-legacy",
        ),
    )

    second_call = processor.process_request.await_args_list[1]
    projected_payload = second_call.args[1].extra_body[
        RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY
    ]
    assert projected_payload["messages"] == [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "legacy assistant reply"}],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "what next?"}],
        },
    ]


@pytest.mark.asyncio
async def test_prepare_responses_execution_rejects_unsupported_backend() -> None:
    """Backends outside the supported Responses matrix must not get silent OpenAI wire."""

    kwargs = build_responses_controller_backend_kwargs()

    async def _resolve_openrouter(request: object, context: object | None = None):
        from src.core.domain.backend_target import BackendTarget

        return BackendTarget(backend="openrouter", model="gpt-4", uri_params={})

    kwargs["backend_model_resolver"].resolve_target = AsyncMock(
        side_effect=_resolve_openrouter
    )

    translation_service = StubTranslationService()
    processor = AsyncMock()
    controller = ResponsesController(
        processor,
        translation_service=translation_service,
        **kwargs,
    )

    responses_request = _responses_request(
        model="openrouter:gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
    )

    with pytest.raises(ResponsesProviderLimitationError) as exc_info:
        await controller._prepare_responses_execution(
            responses_request=responses_request,
        )
    assert exc_info.value.code == "provider_limitation"
    assert exc_info.value.provider == "openrouter"
