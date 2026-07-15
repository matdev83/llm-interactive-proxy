"""Responses-to-chat projection for text-only ACP backends."""

from __future__ import annotations

from typing import Any, cast

from src.core.common.exceptions import ResponsesProviderLimitationError
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses_domain import (
    ResponsesDomainRequest,
    ResponsesOutputItem,
)
from src.core.domain.responses_native_wiring import ACP_RESPONSES_TEXT_ONLY_MODE_KEY
from src.core.domain.responses_resolved_session import ResponsesHistoryItem
from src.core.domain.translators.responses.request import responses_to_domain_request

_EMBEDDED_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
_TEXT_INPUT_ITEM_TYPES = frozenset(
    {
        "message",
        "function_call",
        "function_call_output",
    }
)
_TEXT_CONTENT_PART_TYPES = frozenset({"text", "input_text", "output_text"})
_UNSUPPORTED_FIELDS = frozenset(
    {
        "background",
        "conversation",
        "frequency_penalty",
        "include",
        "n",
        "logit_bias",
        "max_output_tokens",
        "max_tokens",
        "max_tool_calls",
        "parallel_tool_calls",
        "presence_penalty",
        "prompt",
        "response_format",
        "seed",
        "stop",
        "temperature",
        "text",
        "top_p",
        "top_logprobs",
        "tool_choice",
        "tools",
        "truncation",
    }
)


def _embedded_model_effort(model: str) -> str | None:
    suffix = model.rsplit("-", 1)[-1].casefold()
    return suffix if suffix in _EMBEDDED_EFFORTS else None


def _validate_reasoning_effort(request: ResponsesDomainRequest, model: str) -> None:
    if request.reasoning is None:
        return
    effort_raw = request.reasoning.get("effort")
    if effort_raw is None:
        raise ResponsesProviderLimitationError("reasoning", "cursor-cli-acp")
    effort = str(effort_raw).strip().casefold()
    embedded = _embedded_model_effort(model)
    if embedded is None or effort != embedded:
        raise ResponsesProviderLimitationError(
            f"reasoning.effort={effort}", "cursor-cli-acp"
        )


def _input_item_payload(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        return cast(dict[str, Any], item)
    if hasattr(item, "model_dump"):
        payload = item.model_dump(mode="json", exclude_none=True)
        return cast(dict[str, Any], payload) if isinstance(payload, dict) else None
    return None


def _validate_text_only_input(request: ResponsesDomainRequest) -> None:
    # ``ResponsesDomainRequest`` normally types input as a list, but the
    # compatibility path also accepts the valid Responses string form. Keep
    # this boundary value dynamic so model-constructed requests are validated
    # instead of being rejected by static narrowing.
    raw_input: object = getattr(request, "input", None)
    if raw_input is None or isinstance(raw_input, str):
        return
    if not isinstance(raw_input, list):
        raise ResponsesProviderLimitationError("input", "cursor-cli-acp")

    for item in cast(list[Any], raw_input):
        payload = _input_item_payload(item)
        if payload is None:
            raise ResponsesProviderLimitationError("input", "cursor-cli-acp")

        item_type = str(payload.get("type") or "").strip().casefold()
        if item_type not in _TEXT_INPUT_ITEM_TYPES:
            raise ResponsesProviderLimitationError(
                item_type or "input", "cursor-cli-acp"
            )

        content = payload.get("content")
        if content is None or isinstance(content, str):
            continue
        if not isinstance(content, list):
            raise ResponsesProviderLimitationError("input.content", "cursor-cli-acp")

        for part in cast(list[Any], content):
            part_payload = _input_item_payload(part)
            if part_payload is None:
                raise ResponsesProviderLimitationError(
                    "input.content", "cursor-cli-acp"
                )
            part_type = str(part_payload.get("type") or "").strip().casefold()
            if part_type not in _TEXT_CONTENT_PART_TYPES:
                raise ResponsesProviderLimitationError(
                    part_type or "input.content", "cursor-cli-acp"
                )


def _validate_tool_result_continuation(request: ResponsesDomainRequest) -> None:
    """Reject tool-only continuations that ACP cannot replay without data loss."""
    raw_input: object = getattr(request, "input", None)
    if not isinstance(raw_input, list):
        return

    last_user_index = -1
    last_tool_output_index = -1
    for index, item in enumerate(cast(list[Any], raw_input)):
        payload = _input_item_payload(item)
        if payload is None:
            continue
        item_type = str(payload.get("type") or "").strip().casefold()
        if item_type == "function_call_output":
            last_tool_output_index = index
        elif item_type == "message":
            role = str(payload.get("role") or "").strip().casefold()
            if role == "user":
                last_user_index = index

    if last_tool_output_index > last_user_index:
        raise ResponsesProviderLimitationError(
            "input.function_call_output", "cursor-cli-acp"
        )


def _validate_text_only_contract(request: ResponsesDomainRequest, model: str) -> None:
    data = request.model_dump(mode="json", exclude_unset=True)
    for field in sorted(_UNSUPPORTED_FIELDS):
        if field in data and data[field] is not None:
            raise ResponsesProviderLimitationError(field, "cursor-cli-acp")
    if request.extra_body:
        raise ResponsesProviderLimitationError("extra_body", "cursor-cli-acp")
    _validate_text_only_input(request)
    _validate_tool_result_continuation(request)
    _validate_reasoning_effort(request, model)


def project_responses_to_acp_chat(
    request: ResponsesDomainRequest,
    prior_items: list[ResponsesOutputItem] | None,
    *,
    explicit_model: str,
    prior_history: list[ResponsesHistoryItem] | None = None,
) -> CanonicalChatRequest:
    """Project a Responses request onto ACP's canonical chat contract.

    ACP agent runtimes do not expose their tool requests as client-owned function
    calls. This projection therefore fails closed on tool-bearing requests and is
    intentionally suitable only for text-only Planner/Advisor roles.
    """

    _validate_text_only_contract(request, explicit_model)
    payload: dict[str, Any] = request.model_dump(
        mode="json", exclude_unset=True, exclude_none=True
    )
    current_input = payload.pop("input", [])
    combined_input: list[dict[str, Any]] = []
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        # ``instructions`` is a Responses-level system override. ACP only
        # receives the projected chat transcript, so retain it as an explicit
        # system message instead of relying on ``system_prompt`` (which is not
        # part of ``processed_messages`` at the connector boundary).
        combined_input.append(
            {
                "type": "message",
                "role": "system",
                "content": instructions,
            }
        )
    history = prior_history if prior_history is not None else prior_items
    if history:
        # A previous response may have been produced by another provider.  Do
        # not let multimodal or tool-bearing history cross into Cursor's
        # text-only ACP path and disappear during stringification.
        history_request = ResponsesDomainRequest.model_construct(input=history)
        _validate_text_only_input(history_request)
        combined_input.extend(
            item.model_dump(mode="json", exclude_none=True) for item in history
        )
    if isinstance(current_input, str):
        combined_input.append(
            {
                "type": "message",
                "role": "user",
                "content": current_input,
            }
        )
    elif isinstance(current_input, list):
        combined_input.extend(
            cast(dict[str, Any], item)
            for item in cast(list[Any], current_input)
            if isinstance(item, dict)
        )
    payload["input"] = combined_input
    payload["model"] = explicit_model
    payload.pop("previous_response_id", None)
    # The exact model suffix is authoritative. A matching Responses effort is
    # validation-only and must not become a second provider-side selector.
    payload.pop("reasoning", None)
    canonical = responses_to_domain_request(payload)
    return canonical.model_copy(
        update={
            "model": explicit_model,
            "extra_body": {ACP_RESPONSES_TEXT_ONLY_MODE_KEY: True},
        }
    )
