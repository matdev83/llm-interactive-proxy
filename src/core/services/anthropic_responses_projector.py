"""Project Responses domain requests to Anthropic Messages API payloads."""

from __future__ import annotations

import json
from typing import Any

from src.core.common.exceptions import ResponsesProviderLimitationError
from src.core.domain.responses_domain import (
    ResponsesContentPart,
    ResponsesDomainRequest,
    ResponsesInputItem,
    ResponsesOutputItem,
)
from src.core.interfaces.responses_projector import IResponsesBackendProjector

_PROVIDER = "anthropic"

_UNSUPPORTED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "conversation",
        "include",
        "prompt",
        "prompt_cache_key",
        "prompt_cache_retention",
        "reasoning",
        "truncation",
        "store",
        "stream_options",
        "n",
        "top_logprobs",
        "logit_bias",
        "presence_penalty",
        "frequency_penalty",
        "background",
        "session_id",
        "agent",
        "safety_identifier",
        "text",
        "extra_body",
        "parallel_tool_calls",
        "response_format",
        "seed",
    }
)


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw_arguments": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def _tools_openai_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise ResponsesProviderLimitationError("tools", _PROVIDER)
        if tool.get("type") != "function":
            raise ResponsesProviderLimitationError("tools", _PROVIDER)
        fn = tool.get("function")
        if not isinstance(fn, dict):
            raise ResponsesProviderLimitationError("tools", _PROVIDER)
        name = fn.get("name")
        if not isinstance(name, str) or not name:
            raise ResponsesProviderLimitationError("tools", _PROVIDER)
        description = fn.get("description")
        parameters = fn.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}
        if not isinstance(parameters, dict):
            raise ResponsesProviderLimitationError("tools", _PROVIDER)
        entry: dict[str, Any] = {
            "name": name,
            "input_schema": parameters,
        }
        if isinstance(description, str) and description:
            entry["description"] = description
        out.append(entry)
    return out


def _text_parts_from_content_parts(
    parts: list[ResponsesContentPart],
) -> list[str]:
    texts: list[str] = []
    for part in parts:
        if part.type in ("input_text", "output_text", "text"):
            if part.text:
                texts.append(part.text)
        else:
            raise ResponsesProviderLimitationError(
                f"content_part.{part.type}", _PROVIDER
            )
    return texts


def _message_content_from_parts(
    parts: list[ResponsesContentPart] | str | None,
) -> str | list[dict[str, Any]]:
    if parts is None:
        return ""
    if isinstance(parts, str):
        return parts
    blocks: list[dict[str, Any]] = []
    for part in parts:
        if part.type in ("input_text", "output_text", "text"):
            if part.text is not None:
                blocks.append({"type": "text", "text": part.text})
        elif part.type == "input_image" or part.image_url is not None:
            raise ResponsesProviderLimitationError("content_part.image", _PROVIDER)
        else:
            raise ResponsesProviderLimitationError(
                f"content_part.{part.type}", _PROVIDER
            )
    if not blocks:
        return ""
    return blocks


def _tool_use_block(item: ResponsesInputItem | ResponsesOutputItem) -> dict[str, Any]:
    call_id = item.call_id or ""
    name = item.name or ""
    raw_args: str | None
    if isinstance(item, ResponsesInputItem):
        raw_args = item.arguments
    else:
        raw_args = item.arguments
    input_obj = _parse_json_object(raw_args if isinstance(raw_args, str) else None)
    return {
        "type": "tool_use",
        "id": str(call_id),
        "name": str(name),
        "input": input_obj,
    }


def _tool_result_block(call_id: str, output: str | None) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": str(call_id),
        "content": output if output is not None else "",
    }


def _convert_input_items(items: list[ResponsesInputItem]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    pending_tool_use: list[dict[str, Any]] = []
    pending_tool_result: list[dict[str, Any]] = []

    def flush_tool_uses() -> None:
        if pending_tool_use:
            messages.append({"role": "assistant", "content": list(pending_tool_use)})
            pending_tool_use.clear()

    def flush_tool_results() -> None:
        if pending_tool_result:
            messages.append({"role": "user", "content": list(pending_tool_result)})
            pending_tool_result.clear()

    for item in items:
        itype = item.type
        if itype == "message":
            flush_tool_uses()
            flush_tool_results()
            role = item.role or "user"
            if role not in ("user", "assistant", "system", "developer"):
                raise ResponsesProviderLimitationError(
                    f"input_item.message.role={role}", _PROVIDER
                )
            if role in ("system", "developer"):
                prefix = "System" if role == "system" else "Developer"
                if isinstance(item.content, list):
                    texts = _text_parts_from_content_parts(item.content)
                    body = "\n".join(texts)
                elif isinstance(item.content, str):
                    body = item.content
                else:
                    body = ""
                messages.append(
                    {
                        "role": "user",
                        "content": f"[{prefix}]\n{body}".strip(),
                    }
                )
                continue
            content = _message_content_from_parts(item.content)
            messages.append({"role": role, "content": content})
        elif itype == "function_call":
            flush_tool_results()
            pending_tool_use.append(_tool_use_block(item))
        elif itype == "function_call_output":
            flush_tool_uses()
            call_id = item.call_id or ""
            pending_tool_result.append(_tool_result_block(str(call_id), item.output))
        else:
            raise ResponsesProviderLimitationError(f"input_item.{itype}", _PROVIDER)

    flush_tool_uses()
    flush_tool_results()
    return messages


def _convert_output_item(item: ResponsesOutputItem) -> list[dict[str, Any]]:
    otype = item.type
    if otype == "message":
        role = item.role or "assistant"
        if role not in ("user", "assistant"):
            raise ResponsesProviderLimitationError(
                f"prior_output_item.message.role={role}", _PROVIDER
            )
        content = _message_content_from_parts(item.content)
        return [{"role": role, "content": content}]
    if otype == "function_call":
        return [
            {
                "role": "assistant",
                "content": [_tool_use_block(item)],
            }
        ]
    raise ResponsesProviderLimitationError(f"prior_output_item.{otype}", _PROVIDER)


def _assert_no_unsupported_request_fields(req: ResponsesDomainRequest) -> None:
    data = req.model_dump(mode="json", exclude_unset=True)
    for key in _UNSUPPORTED_TOP_LEVEL:
        if key not in data:
            continue
        if data[key] is None:
            continue
        raise ResponsesProviderLimitationError(key, _PROVIDER)

    extras = getattr(req, "__pydantic_extra__", None) or {}
    for key in sorted(extras.keys()):
        raise ResponsesProviderLimitationError(key, _PROVIDER)


class AnthropicResponsesProjector(IResponsesBackendProjector):
    def project(
        self,
        request: ResponsesDomainRequest,
        prior_items: list[ResponsesOutputItem] | None,
    ) -> tuple[dict[str, Any], list[str]]:
        _assert_no_unsupported_request_fields(request)

        messages: list[dict[str, Any]] = []
        if prior_items:
            for out in prior_items:
                messages.extend(_convert_output_item(out))

        messages.extend(_convert_input_items(list(request.input)))

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
        }

        if request.instructions is not None and request.instructions != "":
            payload["system"] = request.instructions

        if request.tools is not None:
            payload["tools"] = _tools_openai_to_anthropic(
                [t for t in request.tools if isinstance(t, dict)]
            )

        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice

        if request.stream is not None:
            payload["stream"] = bool(request.stream)

        if request.temperature is not None:
            payload["temperature"] = request.temperature

        if request.top_p is not None:
            payload["top_p"] = request.top_p

        if request.stop is not None:
            if isinstance(request.stop, str):
                payload["stop_sequences"] = [request.stop]
            elif isinstance(request.stop, list):
                payload["stop_sequences"] = list(request.stop)
            else:
                raise ResponsesProviderLimitationError("stop", _PROVIDER)

        if request.metadata is not None:
            payload["metadata"] = dict(request.metadata)

        if request.user is not None:
            meta = dict(payload.get("metadata") or {})
            if "user_id" in meta and meta["user_id"] != request.user:
                raise ResponsesProviderLimitationError("metadata.user_id", _PROVIDER)
            meta["user_id"] = request.user
            payload["metadata"] = meta

        max_out = request.max_output_tokens
        max_tok = request.max_tokens
        if max_out is not None and max_tok is not None and max_out != max_tok:
            raise ResponsesProviderLimitationError(
                "max_tokens_vs_max_output_tokens", _PROVIDER
            )
        if max_out is not None:
            payload["max_tokens"] = max_out
        elif max_tok is not None:
            payload["max_tokens"] = max_tok

        return payload, []
