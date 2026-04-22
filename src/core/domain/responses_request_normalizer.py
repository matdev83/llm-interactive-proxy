"""Normalize raw Responses API request payloads into typed domain models."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.core.common.exceptions import ResponsesValidationError
from src.core.domain.responses_domain import (
    ResponsesContentPart,
    ResponsesDomainRequest,
    ResponsesInputItem,
)


def _map_pydantic_validation(exc: ValidationError) -> ResponsesValidationError:
    errs = exc.errors()
    if not errs:
        return ResponsesValidationError(
            str(exc),
            code="invalid_request_error",
            param=None,
        )
    first = errs[0]
    loc = first.get("loc") or ()
    param: str | None = None
    if len(loc) > 0:
        tail = [str(x) for x in loc]
        if tail:
            param = ".".join(tail)
    msg = str(first.get("msg") or str(exc))
    return ResponsesValidationError(
        msg,
        code="invalid_request_error",
        param=param,
    )


class ResponsesRequestNormalizer:
    def normalize(self, raw: dict[str, Any]) -> ResponsesDomainRequest:
        payload = raw.copy()
        model = payload.get("model")
        if model is None or (isinstance(model, str) and model.strip() == ""):
            raise ResponsesValidationError(
                "Missing required parameter: 'model'.",
                code="missing_required_parameter",
                param="model",
            )
        if not isinstance(model, str):
            raise ResponsesValidationError(
                "Invalid type for 'model': expected a string.",
                code="invalid_type",
                param="model",
            )

        input_present = "input" in payload
        if "messages" in payload and input_present:
            raise ResponsesValidationError(
                "Cannot specify both 'messages' and 'input' for the Responses API.",
                code="invalid_request_error",
                param="input",
            )

        payload.pop("messages", None)
        input_raw = payload.pop("input", None) if input_present else None

        normalized_input = self._coerce_input(input_raw)

        body: dict[str, Any] = {
            **payload,
            "model": model.strip(),
            "input": normalized_input,
        }
        if body.get("stream") is None:
            body.pop("stream", None)
        try:
            return ResponsesDomainRequest.model_validate(body)
        except ValidationError as exc:
            raise _map_pydantic_validation(exc) from exc

    def _coerce_input(self, value: Any) -> list[ResponsesInputItem]:
        if value is None:
            return []

        if isinstance(value, str):
            return [
                ResponsesInputItem(
                    type="message",
                    role="user",
                    content=[
                        ResponsesContentPart(type="input_text", text=value),
                    ],
                )
            ]

        if isinstance(value, dict):
            return [self._validate_input_item(value)]

        if isinstance(value, list):
            items: list[ResponsesInputItem] = []
            for idx, entry in enumerate(value):
                if not isinstance(entry, dict):
                    raise ResponsesValidationError(
                        f"Invalid type for 'input[{idx}]': expected an object.",
                        code="invalid_type",
                        param=f"input.{idx}",
                    )
                items.append(self._validate_input_item(entry))
            return items

        raise ResponsesValidationError(
            "Invalid type for 'input': expected a string, array, or object.",
            code="invalid_type",
            param="input",
        )

    def _validate_input_item(self, entry: dict[str, Any]) -> ResponsesInputItem:
        shorthand = self._maybe_normalize_message_shorthand(entry)
        if shorthand is not None:
            return shorthand
        try:
            return ResponsesInputItem.model_validate(entry)
        except ValidationError as exc:
            raise _map_pydantic_validation(exc) from exc

    def _maybe_normalize_message_shorthand(
        self, entry: dict[str, Any]
    ) -> ResponsesInputItem | None:
        if "type" in entry:
            return None

        role = entry.get("role")
        if not isinstance(role, str) or role.strip() == "":
            return None

        if "content" not in entry:
            return None

        content = entry.get("content")
        if isinstance(content, str):
            normalized_content: list[ResponsesContentPart] | str | None = [
                ResponsesContentPart(type="input_text", text=content)
            ]
        elif isinstance(content, list):
            normalized_content = content
        elif isinstance(content, dict):
            try:
                normalized_content = [ResponsesContentPart.model_validate(content)]
            except ValidationError:
                return None
        elif content is None:
            normalized_content = None
        else:
            return None

        normalized_entry = dict(entry)
        normalized_entry["type"] = "message"
        normalized_entry["role"] = role.strip()
        normalized_entry["content"] = normalized_content
        try:
            return ResponsesInputItem.model_validate(normalized_entry)
        except ValidationError:
            return None
