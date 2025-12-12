from __future__ import annotations

import json
import logging
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
)
from src.core.domain.translation_utils.schema_validation import (
    validate_json_against_schema,
)

logger = logging.getLogger(__name__)


def enhance_structured_output_response(
    response: ChatResponse,
    original_request_extra_body: dict[str, Any] | None = None,
) -> ChatResponse:
    if not original_request_extra_body:
        return response

    response_format = original_request_extra_body.get("response_format")
    if not response_format or response_format.get("type") != "json_schema":
        return response

    json_schema_info = response_format.get("json_schema", {})
    schema = json_schema_info.get("schema", {})
    if not schema:
        return response

    enhanced_choices: list[ChatCompletionChoice] = []
    for choice in response.choices:
        if not choice.message or not choice.message.content:
            enhanced_choices.append(choice)
            continue

        content = str(choice.message.content).strip()
        try:
            parsed_json = json.loads(content)
            if not isinstance(parsed_json, dict):
                enhanced_choices.append(choice)
                continue

            is_valid, error_msg = validate_json_against_schema(parsed_json, schema)
            if is_valid:
                enhanced_choices.append(choice)
                continue

            repaired_json = attempt_json_repair(parsed_json, schema, error_msg)
            if repaired_json is None:
                enhanced_choices.append(choice)
                continue

            repaired_content = json.dumps(repaired_json, indent=2)
            enhanced_message = ChatCompletionChoiceMessage(
                role=choice.message.role,
                content=repaired_content,
                tool_calls=choice.message.tool_calls,
            )
            enhanced_choices.append(
                ChatCompletionChoice(
                    index=choice.index,
                    message=enhanced_message,
                    finish_reason=choice.finish_reason,
                )
            )
        except json.JSONDecodeError:
            extracted = extract_and_repair_json(content, schema)
            if extracted is None:
                enhanced_choices.append(choice)
                continue

            enhanced_message = ChatCompletionChoiceMessage(
                role=choice.message.role,
                content=extracted,
                tool_calls=choice.message.tool_calls,
            )
            enhanced_choices.append(
                ChatCompletionChoice(
                    index=choice.index,
                    message=enhanced_message,
                    finish_reason=choice.finish_reason,
                )
            )

    return CanonicalChatResponse(
        id=response.id,
        object=response.object,
        created=response.created,
        model=response.model,
        choices=enhanced_choices,
        usage=response.usage,
        system_fingerprint=getattr(response, "system_fingerprint", None),
    )


def attempt_json_repair(
    json_data: dict[str, Any], schema: dict[str, Any], error_msg: str | None
) -> dict[str, Any] | None:
    try:
        repaired = dict(json_data)

        if schema.get("type") == "object":
            required = schema.get("required", [])
            properties = schema.get("properties", {})

            for prop in required:
                if prop in repaired:
                    continue

                prop_schema = properties.get(prop, {})
                prop_type = prop_schema.get("type", "string")

                if prop_type == "string":
                    repaired[prop] = ""
                elif prop_type == "number":
                    repaired[prop] = 0.0
                elif prop_type == "integer":
                    repaired[prop] = 0
                elif prop_type == "boolean":
                    repaired[prop] = False
                elif prop_type == "array":
                    repaired[prop] = []
                elif prop_type == "object":
                    repaired[prop] = {}
                else:
                    repaired[prop] = None

        is_valid, _ = validate_json_against_schema(repaired, schema)
        return repaired if is_valid else None
    except Exception:
        return None


def iter_json_candidates(
    content: str,
    *,
    max_candidates: int = 20,
    max_object_size: int = 512 * 1024,
) -> list[str]:
    candidates: list[str] = []
    depth = 0
    start_index: int | None = None
    escape_next = False
    string_delimiter: str | None = None

    for index, char in enumerate(content):
        if string_delimiter is not None:
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == string_delimiter:
                string_delimiter = None
            continue

        if char in ('"', "'"):
            string_delimiter = char
            continue

        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start_index is not None:
                candidate = content[start_index : index + 1]
                start_index = None
                if len(candidate) > max_object_size:
                    logger.warning(
                        "Skipping oversized JSON candidate (%d bytes)",
                        len(candidate),
                    )
                    continue
                candidates.append(candidate)
                if len(candidates) >= max_candidates:
                    break

    return candidates


def extract_and_repair_json(content: str, schema: dict[str, Any]) -> str | None:
    try:
        for candidate in iter_json_candidates(content):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue

            if not isinstance(parsed, dict):
                continue

            repaired = attempt_json_repair(parsed, schema, None)
            if repaired is not None:
                return json.dumps(repaired, indent=2)

        return None
    except Exception:
        return None
