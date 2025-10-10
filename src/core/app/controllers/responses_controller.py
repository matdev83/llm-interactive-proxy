"""Responses Controller handling OpenAI Responses API endpoints."""

import asyncio
import logging
import re
from typing import Any, cast

import sre_parse
from sre_constants import MAXREPEAT

from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from src.core.common.exceptions import InitializationError, LLMProxyError
from src.core.domain.responses_api import ResponsesRequest
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.translation_service_interface import (
    ITranslationService,
)
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi

logger = logging.getLogger(__name__)


class ResponsesController:
    """Controller for Responses API endpoints."""

    _MAX_REGEX_PATTERN_LENGTH = 512

    def __init__(
        self,
        request_processor: IRequestProcessor,
        translation_service: ITranslationService | None = None,
    ) -> None:
        """Initialize the controller.

        Args:
            request_processor: The request processor service
        """
        self._processor = request_processor
        if translation_service is None:
            raise InitializationError(
                "Translation service must be provided by the DI container"
            )

        self._translation_service = translation_service

    async def handle_responses_request(
        self,
        request: Request,
        request_data: ResponsesRequest | dict[str, Any],
    ) -> Response:
        """Handle Responses API requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data as a ResponsesRequest

        Returns:
            An HTTP response
        """
        # Validate and normalize the incoming request payload
        try:
            responses_request = (
                request_data
                if isinstance(request_data, ResponsesRequest)
                else ResponsesRequest.model_validate(request_data)
            )
        except ValidationError as exc:
            raise self._map_validation_error(exc) from exc

        # Extract request metadata for logging
        request_id = getattr(request.state, "request_id", None) or f"req-{id(request)}"
        model = responses_request.model
        has_schema = bool(
            getattr(responses_request, "response_format", None)
            and getattr(responses_request.response_format, "json_schema", None)
        )
        schema_name = None
        if has_schema:
            json_schema = responses_request.response_format.json_schema
            schema_name = getattr(json_schema, "name", "unnamed")

            # Perform comprehensive JSON schema validation
            try:
                self._validate_json_schema(json_schema.get_schema())
                logger.debug(
                    f"JSON schema validation passed - request_id={request_id}, schema_name={schema_name}"
                )
            except Exception as e:
                logger.error(
                    f"JSON schema validation failed - request_id={request_id}, schema_name={schema_name}, error={e}"
                )
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "message": f"Invalid JSON schema: {e!s}",
                            "type": "invalid_schema",
                            "code": "invalid_schema",
                        }
                    },
                )

        logger.info(
            f"Responses API request received - request_id={request_id}, model={model}, "
            f"has_schema={has_schema}, schema_name={schema_name}"
        )

        try:
            # Convert ResponsesRequest to internal ChatRequest format using TranslationService
            translation_service = self._translation_service

            # Log schema validation attempt if schema is present
            if has_schema:
                logger.debug(
                    f"Schema validation requested - request_id={request_id}, schema_name={schema_name}, "
                    f"strict={getattr(responses_request.response_format.json_schema, 'strict', True)}"
                )

            domain_request = translation_service.to_domain_request(
                responses_request, source_format="responses"
            )

            logger.debug(
                f"Request translation successful - request_id={request_id}, "
                f"domain_model={domain_request.model}, processor_type={type(self._processor).__name__}"
            )
            if self._processor is None:
                raise HTTPException(status_code=500, detail="Processor is None")

            # Convert FastAPI Request to RequestContext and process via core processor
            ctx = fastapi_to_domain_request_context(request, attach_original=True)
            # Attach domain request so session resolver can read session_id/extra_body
            import contextlib

            with contextlib.suppress(Exception):
                ctx.domain_request = domain_request  # type: ignore[attr-defined]

            # Add schema information to context for structured output middleware
            if (
                hasattr(responses_request, "response_format")
                and responses_request.response_format
            ):
                response_format = responses_request.response_format
                if (
                    hasattr(response_format, "json_schema")
                    and response_format.json_schema
                ):
                    json_schema = response_format.json_schema
                    # Add schema to context for middleware processing
                    if ctx.processing_context is None:
                        ctx.processing_context = {}
                    schema_dict = json_schema.get_schema()
                    if not isinstance(schema_dict, dict) or "type" not in schema_dict:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": {
                                    "message": "Invalid JSON schema: missing 'type' field",
                                    "type": "invalid_request_error",
                                    "code": "invalid_schema",
                                }
                            },
                        )

                    ctx.processing_context.update(
                        {
                            "response_schema": schema_dict,
                            "strict_schema_validation": getattr(
                                json_schema, "strict", True
                            ),
                            "schema_name": getattr(json_schema, "name", "unknown"),
                            "request_id": request_id,
                        }
                    )

                    logger.debug(
                        f"Schema context added to processing pipeline - request_id={request_id}, "
                        f"schema_name={schema_name}, strict={getattr(json_schema, 'strict', True)}"
                    )
            # Process the request using the request processor
            logger.debug(
                f"Processing request through pipeline - request_id={request_id}"
            )
            response = await self._processor.process_request(ctx, domain_request)

            # Convert domain response to FastAPI response
            # Ensure we await the response if it's a coroutine
            if asyncio.iscoroutine(response):
                response = await response

            logger.debug(
                f"Request processing completed - request_id={request_id}, response_type={type(response).__name__}"
            )

            # Check if this is a streaming response
            from src.core.domain.responses import StreamingResponseEnvelope

            if isinstance(response, StreamingResponseEnvelope):
                logger.debug(f"Returning streaming response - request_id={request_id}")

                # For streaming responses, use FastAPI's StreamingResponse
                async def stream_content():
                    """Convert ProcessedResponse objects to Responses API SSE format."""
                    import json
                    import time

                    response_id = f"resp_{int(time.time())}_{id(response)}"
                    created_timestamp = int(time.time())
                    last_chunk_model = domain_request.model

                    async for chunk in response.content:
                        try:
                            chunk_content = ""
                            chunk_metadata: dict[str, Any] = {}
                            chunk_payload: dict[str, Any] | None = None

                            if isinstance(chunk, ProcessedResponse):
                                chunk_content = chunk.content or ""
                                chunk_metadata = chunk.metadata or {}
                                if isinstance(chunk.content, dict):
                                    chunk_payload = chunk.content
                            elif isinstance(chunk, dict):
                                chunk_content = str(chunk.get("content", ""))
                                chunk_metadata = chunk.get("metadata", {}) or {}
                                chunk_payload = chunk
                            elif hasattr(chunk, "content"):
                                chunk_content = getattr(chunk, "content", "") or ""
                                chunk_metadata = getattr(chunk, "metadata", {}) or {}
                                if isinstance(chunk_content, dict):
                                    chunk_payload = chunk_content
                            elif isinstance(chunk, str):
                                chunk_content = chunk
                            else:
                                chunk_content = str(chunk)

                            chunk_id = chunk_metadata.get("id") or response_id
                            chunk_model = (
                                chunk_metadata.get("model") or domain_request.model
                            )
                            chunk_created = (
                                chunk_metadata.get("created") or created_timestamp
                            )

                            finish_reason = chunk_metadata.get("finish_reason")
                            delta: dict[str, Any] = {}

                            if chunk_payload and isinstance(chunk_payload, dict):
                                chunk_id = chunk_payload.get("id", chunk_id)
                                chunk_model = chunk_payload.get("model", chunk_model)
                                chunk_created = chunk_payload.get(
                                    "created", chunk_created
                                )

                                choices = chunk_payload.get("choices")
                                if isinstance(choices, list) and choices:
                                    primary_choice = choices[0] or {}
                                    delta_payload = primary_choice.get("delta") or {}
                                    if isinstance(delta_payload, dict):
                                        delta = dict(delta_payload)
                                    finish_reason = (
                                        primary_choice.get("finish_reason")
                                        or finish_reason
                                    )

                            if not delta and chunk_content:
                                delta["content"] = chunk_content

                            # Normalize delta content to string when present
                            content_value = delta.get("content")
                            if content_value is not None and not isinstance(
                                content_value, str
                            ):
                                delta["content"] = json.dumps(content_value)

                            # Merge tool calls from delta or chunk metadata
                            tool_calls = delta.get("tool_calls") or chunk_metadata.get(
                                "tool_calls"
                            )
                            if tool_calls:
                                normalized_calls: list[dict[str, Any]] = []
                                for tool_call in tool_calls:
                                    if hasattr(tool_call, "model_dump"):
                                        call_data = tool_call.model_dump()
                                    elif isinstance(tool_call, dict):
                                        call_data = dict(tool_call)
                                    else:
                                        function = getattr(tool_call, "function", None)
                                        call_data = {
                                            "id": getattr(tool_call, "id", ""),
                                            "type": getattr(
                                                tool_call, "type", "function"
                                            ),
                                            "function": {
                                                "name": getattr(function, "name", ""),
                                                "arguments": getattr(
                                                    function, "arguments", "{}"
                                                ),
                                            },
                                        }

                                    function_payload = call_data.get("function")
                                    if isinstance(function_payload, dict):
                                        arguments = function_payload.get("arguments")
                                        if isinstance(arguments, dict | list):
                                            function_payload["arguments"] = json.dumps(
                                                arguments
                                            )
                                        elif arguments is None:
                                            function_payload["arguments"] = "{}"

                                    normalized_calls.append(call_data)

                                delta["tool_calls"] = normalized_calls

                            if not delta:
                                delta["content"] = ""

                            choice_payload: dict[str, Any] = {
                                "index": 0,
                                "delta": delta,
                            }
                            if finish_reason:
                                choice_payload["finish_reason"] = finish_reason

                            streaming_chunk = {
                                "id": chunk_id,
                                "object": "response.chunk",
                                "created": chunk_created,
                                "model": chunk_model,
                                "choices": [choice_payload],
                            }

                            last_chunk_model = chunk_model

                            # Format as Server-Sent Events
                            yield f"data: {json.dumps(streaming_chunk)}\n\n"

                        except Exception as e:
                            logger.warning(
                                f"Error processing streaming chunk - request_id={request_id}, error={e}"
                            )
                            # Continue with next chunk instead of breaking the stream
                            continue

                    # Send final chunk to indicate stream completion
                    final_chunk = {
                        "id": response_id,
                        "object": "response.chunk",
                        "created": created_timestamp,
                        "model": last_chunk_model,
                        "choices": [{"index": 0, "finish_reason": "stop", "delta": {}}],
                    }
                    yield f"data: {json.dumps(final_chunk)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    content=stream_content(),
                    status_code=200,
                    media_type="text/event-stream",
                    headers={
                        "cache-control": "no-cache",
                        "connection": "keep-alive",
                        "content-type": "text/event-stream",
                        "access-control-allow-origin": "*",
                        "access-control-allow-headers": "*",
                    },
                )

            # Convert domain response to Responses API format using TranslationService
            def _ensure_responses_schema(content: object) -> object:
                try:
                    from src.core.domain.chat import ChatResponse

                    logger.debug(
                        f"Converting response to Responses API format - request_id={request_id}, content_type={type(content).__name__}"
                    )

                    # If it's already a ChatResponse, use TranslationService to convert
                    if isinstance(content, ChatResponse):
                        converted_response = (
                            translation_service.from_domain_to_responses_response(
                                content
                            )
                        )
                        logger.debug(
                            f"Response converted via TranslationService - request_id={request_id}"
                        )
                        return converted_response

                    # If it's a dict that looks like a ChatResponse, convert it first
                    if isinstance(content, dict) and "choices" in content:
                        try:
                            chat_response = ChatResponse(**content)
                            converted_response = (
                                translation_service.from_domain_to_responses_response(
                                    chat_response
                                )
                            )
                            logger.debug(
                                f"Response converted from dict via TranslationService - request_id={request_id}"
                            )
                            return converted_response
                        except Exception as e:
                            logger.warning(
                                f"Failed to convert dict to ChatResponse - request_id={request_id}, error={e}"
                            )
                            # If conversion fails, fall back to manual conversion

                    # Fallback: manual conversion for other formats
                    import json as _json
                    import time as _time
                    import uuid as _uuid

                    # If already in expected schema, return as-is
                    # Handle Anthropic-style message dict -> Responses API
                    if (
                        isinstance(content, dict)
                        and content.get("type") == "message"
                        and isinstance(content.get("content"), list)
                    ):
                        # Extract text blocks
                        text_parts: list[str] = []
                        for block in content.get("content", []):
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text":
                                part_text = block.get("text") or ""
                                if part_text:
                                    text_parts.append(str(part_text))

                        text = "\n\n".join(text_parts).strip()
                        stop_reason = content.get("stop_reason") or "stop"
                        if stop_reason == "end_turn":
                            finish_reason = "stop"
                        elif stop_reason == "max_tokens":
                            finish_reason = "length"
                        else:
                            finish_reason = str(stop_reason)

                        # Try to parse the content as JSON for structured output
                        parsed = None
                        try:
                            if text.strip():
                                parsed = _json.loads(text)
                                logger.debug(
                                    f"Successfully parsed structured output - request_id={request_id}"
                                )
                        except (_json.JSONDecodeError, ValueError) as e:
                            logger.debug(
                                f"Content is not valid JSON, leaving unparsed - request_id={request_id}, error={e}"
                            )
                            # If parsing fails, leave parsed as None

                        usage = content.get("usage") or {}
                        responses_usage = {
                            "prompt_tokens": usage.get("input_tokens", 0),
                            "completion_tokens": usage.get("output_tokens", 0),
                            "total_tokens": (usage.get("input_tokens", 0) or 0)
                            + (usage.get("output_tokens", 0) or 0),
                        }

                        return {
                            "id": content.get("id", f"resp-{_uuid.uuid4().hex[:16]}"),
                            "object": "response",
                            "created": int(_time.time()),
                            "model": content.get("model", domain_request.model),
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": text,
                                        "parsed": parsed,
                                    },
                                    "finish_reason": finish_reason,
                                }
                            ],
                            "usage": responses_usage,
                        }

                    # Normalize simple string into Responses API format
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, bytes):
                        text = content.decode("utf-8", errors="ignore")
                    else:
                        # Best-effort stringify for non-dict/list types
                        try:
                            text = _json.dumps(content)
                        except Exception:
                            text = str(content)

                    # Try to parse the content as JSON for structured output
                    parsed = None
                    try:
                        if text.strip():
                            parsed = _json.loads(text)
                            logger.debug(
                                f"Successfully parsed fallback structured output - request_id={request_id}"
                            )
                    except (_json.JSONDecodeError, ValueError) as e:
                        logger.debug(
                            f"Fallback content is not valid JSON, leaving unparsed - request_id={request_id}, error={e}"
                        )
                        # If parsing fails, leave parsed as None

                    return {
                        "id": f"resp-{_uuid.uuid4().hex[:16]}",
                        "object": "response",
                        "created": int(_time.time()),
                        "model": domain_request.model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": text,
                                    "parsed": parsed,
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
                except Exception as e:
                    logger.warning(
                        f"Error in response conversion, returning original content - request_id={request_id}, error={e}"
                    )
                    return content

            final_response = domain_response_to_fastapi(
                response, content_converter=_ensure_responses_schema
            )

            logger.info(
                f"Responses API request completed successfully - request_id={request_id}"
            )
            return final_response

        except LLMProxyError as e:
            logger.error(
                f"LLM Proxy error in Responses API - request_id={request_id}, error={e}"
            )
            # Map domain exceptions to HTTP exceptions
            raise map_domain_exception_to_http_exception(e)
        except HTTPException as e:
            logger.error(
                f"HTTP error in Responses API - request_id={request_id}, status={e.status_code}, detail={e.detail}"
            )
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Log and convert other exceptions to HTTP exceptions
            logger.error(
                f"Unexpected error handling Responses API request - request_id={request_id}, error={e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": "An internal server error occurred while processing your request.",
                        "type": "internal_server_error",
                        "code": "internal_error",
                    }
                },
            )

    @staticmethod
    def _map_validation_error(exc: ValidationError) -> HTTPException:
        """Convert validation errors into HTTP exceptions with appropriate status codes."""

        errors = exc.errors()
        for error in errors:
            loc = error.get("loc", ())
            if any(part in {"schema", "schema_dict"} for part in loc):
                message = error.get("msg", "Invalid JSON schema")
                if message.lower().startswith("value error, "):
                    message = message[12:]
                return HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "message": f"Invalid JSON schema: {message}",
                            "type": "invalid_request_error",
                            "code": "invalid_schema",
                        }
                    },
                )

        # For other validation errors, use OpenAI-style error format
        # Simplify error handling to avoid mypy issues with ValidationError loc field
        return HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "Invalid request format. Please check your request parameters and try again.",
                    "type": "invalid_request_error",
                    "code": "invalid_request",
                }
            },
        )

    @staticmethod
    def _validate_json_schema(schema: dict[str, Any]) -> None:
        """
        Validate a JSON schema for correctness and completeness.

        Args:
            schema: The JSON schema to validate

        Raises:
            ValueError: If the schema is invalid
        """
        if not isinstance(schema, dict):
            raise ValueError("Schema must be a dictionary")

        # Check for required fields
        ResponsesController._ensure_safe_regex_patterns(schema)

        if "type" not in schema:
            raise ValueError("Schema must have a 'type' field")

        # Basic structure validation
        schema_type_raw = schema["type"]
        if isinstance(schema_type_raw, str):
            schema_types = [schema_type_raw]
        elif isinstance(schema_type_raw, (list, tuple, set)):
            schema_types = [
                str(t) for t in schema_type_raw if isinstance(t, (str, bytes))
            ]
        else:
            schema_types = [str(schema_type_raw)]

        if "object" in schema_types:
            # Objects can describe their shape via properties, patternProperties,
            # or references. Require at least one structural keyword so callers
            # can use $ref-only schemas without triggering false positives.
            object_keywords = {
                "properties",
                "patternProperties",
                "additionalProperties",
                "$ref",
                "allOf",
                "anyOf",
                "oneOf",
            }
            if not any(key in schema for key in object_keywords):
                raise ValueError(
                    "Object schemas must declare properties, patternProperties, "
                    "additionalProperties, or use a composition/ref keyword"
                )

            properties = schema.get("properties")
            if properties is not None and not isinstance(properties, dict):
                raise ValueError("Properties must be a dictionary")

            if isinstance(properties, dict):
                # Validate each property
                for prop_name, prop_schema in properties.items():
                    if not isinstance(prop_schema, dict):
                        raise ValueError(
                            f"Property '{prop_name}' schema must be a dictionary"
                        )

                    allowed_structural_keywords = {
                        "type",
                        "$ref",
                        "anyOf",
                        "allOf",
                        "oneOf",
                        "enum",
                        "const",
                        "properties",
                        "patternProperties",
                        "items",
                        "contains",
                        "if",
                        "then",
                        "else",
                        "not",
                        "dependentSchemas",
                    }

                    if "type" not in prop_schema and not any(
                        key in prop_schema for key in allowed_structural_keywords
                    ):
                        raise ValueError(
                            f"Property '{prop_name}' must define a type or a "
                            "supported schema keyword"
                        )

        if "array" in schema_types:
            # Arrays should have items; allow both dict schemas and tuple-style lists
            if "items" not in schema:
                raise ValueError("Array schemas must have an 'items' field")

            items_schema = schema["items"]
            if not isinstance(items_schema, (dict, list, tuple, bool)):
                raise ValueError("Items schema must be a dictionary, list, or boolean")

        primitive_types = {"string", "number", "integer", "boolean", "null"}
        known_types = primitive_types | {"object", "array"}
        unknown_types = [t for t in schema_types if t not in known_types]
        for unknown in unknown_types:
            logger.warning(f"Unusual schema type detected: {unknown}")

        # Validate additional properties if present
        if "additionalProperties" in schema:
            additional_props = schema["additionalProperties"]
            if not isinstance(additional_props, (bool, dict)):
                raise ValueError("additionalProperties must be a boolean or schema")

        # Validate required fields if present
        if "required" in schema:
            required = schema["required"]
            if not isinstance(required, list):
                raise ValueError("Required field must be a list")

            if "object" in schema_types and "properties" in schema:
                properties = schema["properties"]
                for req_field in required:
                    if req_field not in properties:
                        raise ValueError(
                            f"Required field '{req_field}' not found in properties"
                        )

        # Validate enum if present
        if "enum" in schema:
            enum_values = schema["enum"]
            if not isinstance(enum_values, list) or len(enum_values) == 0:
                raise ValueError("Enum must be a non-empty list")

    @staticmethod
    def _ensure_safe_regex_patterns(schema: dict[str, Any]) -> None:
        """Validate regex patterns in a schema to avoid catastrophic backtracking."""

        stack: list[tuple[Any, str]] = [(schema, "$")]
        visited: set[int] = set()

        while stack:
            node, location = stack.pop()
            node_id = id(node)
            if node_id in visited:
                continue
            visited.add(node_id)

            if isinstance(node, dict):
                pattern = node.get("pattern")
                if isinstance(pattern, str):
                    ResponsesController._validate_single_regex(pattern, f"{location}.pattern")

                pattern_properties = node.get("patternProperties")
                if isinstance(pattern_properties, dict):
                    for regex_key, sub_schema in pattern_properties.items():
                        if isinstance(regex_key, str):
                            ResponsesController._validate_single_regex(
                                regex_key,
                                f"{location}.patternProperties[{regex_key}]",
                            )
                        if isinstance(sub_schema, (dict, list)):
                            stack.append(
                                (sub_schema, f"{location}.patternProperties.{regex_key}")
                            )

                for key, value in node.items():
                    if key == "patternProperties":
                        continue
                    if isinstance(value, (dict, list)):
                        stack.append((value, f"{location}.{key}"))

            elif isinstance(node, list):
                for index, item in enumerate(node):
                    if isinstance(item, (dict, list)):
                        stack.append((item, f"{location}[{index}]"))

    @staticmethod
    def _validate_single_regex(pattern: str, location: str) -> None:
        """Validate an individual regex for potential ReDoS characteristics."""

        if len(pattern) > ResponsesController._MAX_REGEX_PATTERN_LENGTH:
            raise ValueError(
                "Regex pattern too long: "
                f"{location} has {len(pattern)} characters (limit is {ResponsesController._MAX_REGEX_PATTERN_LENGTH})"
            )

        try:
            parsed = sre_parse.parse(pattern)
        except re.error as exc:  # pragma: no cover - invalid regex handled elsewhere
            raise ValueError(
                f"Invalid regex pattern at {location}: {exc.args[0]}"
            ) from exc

        if ResponsesController._contains_nested_unbounded_repeat(parsed):
            raise ValueError(
                "Regex pattern contains nested unbounded quantifiers which "
                f"can lead to catastrophic backtracking: {location}"
            )

    @staticmethod
    def _contains_nested_unbounded_repeat(
        subpattern: sre_parse.SubPattern, inside_unbounded: bool = False
    ) -> bool:
        """Detect nested unbounded repeats within a parsed regex pattern."""

        for token in subpattern:
            operator, argument = token

            if operator in {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT}:
                min_repeat, max_repeat, nested = argument
                is_unbounded = max_repeat == MAXREPEAT

                if inside_unbounded and is_unbounded:
                    return True

                if ResponsesController._contains_nested_unbounded_repeat(
                    nested, inside_unbounded=is_unbounded or inside_unbounded
                ):
                    return True

                continue

            if operator == sre_parse.SUBPATTERN:
                nested = argument[-1]
                if ResponsesController._contains_nested_unbounded_repeat(
                    nested, inside_unbounded=inside_unbounded
                ):
                    return True
                continue

            if operator == sre_parse.BRANCH:
                _, branches = argument
                for branch in branches:
                    if ResponsesController._contains_nested_unbounded_repeat(
                        branch, inside_unbounded=inside_unbounded
                    ):
                        return True
                continue

            if operator in {sre_parse.ASSERT, sre_parse.ASSERT_NOT}:
                if ResponsesController._contains_nested_unbounded_repeat(
                    argument[1], inside_unbounded=inside_unbounded
                ):
                    return True

        return False


def get_responses_controller(service_provider: IServiceProvider) -> ResponsesController:
    """Create a responses controller using the service provider.

    Args:
        service_provider: The service provider to use

    Returns:
        A configured responses controller

    Raises:
        Exception: If the request processor could not be found or created
    """
    try:
        from src.core.services.request_processor_service import RequestProcessor
        from src.core.services.translation_service import TranslationService

        # Resolve request processor strictly through the DI container.
        request_processor = service_provider.get_service(
            cast(type, IRequestProcessor)
        )  # type: ignore[type-abstract]
        if request_processor is None:
            request_processor = service_provider.get_service(RequestProcessor)

        if request_processor is None:
            raise InitializationError(
                "RequestProcessor is not registered in the service provider",
            )

        # Resolve optional translation service from DI (may be None).
        translation_service = service_provider.get_service(
            cast(type, ITranslationService)
        )  # type: ignore[type-abstract]
        if translation_service is None:
            translation_service = service_provider.get_service(TranslationService)
        if translation_service is None:
            raise InitializationError(
                "TranslationService is not registered in the service provider",
            )

        return ResponsesController(
            request_processor,
            translation_service=translation_service,
        )
    except Exception as e:
        raise InitializationError(f"Failed to create ResponsesController: {e}") from e
