from __future__ import annotations

import os
from contextlib import suppress
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.translation_utils import media_utils
from src.core.domain.translators.gemini.schema import sanitize_gemini_parameters


def gemini_to_domain_request(request: Any) -> CanonicalChatRequest:
    """Translate a Gemini request to a CanonicalChatRequest."""
    from src.core.domain.gemini_translation import (
        gemini_request_to_canonical_request,
    )

    return gemini_request_to_canonical_request(request)


def from_domain_to_gemini_request(request: CanonicalChatRequest) -> dict[str, Any]:
    """Translate a CanonicalChatRequest to a Gemini request."""
    import logging

    logger = logging.getLogger(__name__)

    _validate_request_parameters(request)

    config: dict[str, Any] = {}
    if request.top_k is not None:
        config["topK"] = request.top_k
    if request.top_p is not None:
        config["topP"] = request.top_p
    if request.temperature is not None:
        config["temperature"] = request.temperature
    max_output = request.max_completion_tokens or request.max_tokens
    if max_output is not None:
        config["maxOutputTokens"] = max_output
    if request.stop:
        config["stopSequences"] = _normalize_stop_sequences(request.stop)

    if request.n is not None and request.n > 1:
        config["candidateCount"] = request.n
    if request.seed is not None:
        config["seed"] = request.seed
    if request.presence_penalty is not None:
        config["presencePenalty"] = request.presence_penalty
    if request.frequency_penalty is not None:
        config["frequencyPenalty"] = request.frequency_penalty
    if request.logprobs is not None:
        config["responseLogprobs"] = request.logprobs
    if request.top_logprobs is not None:
        config["logprobs"] = request.top_logprobs

    def _resolve_thinking_budget(
        reasoning_effort: str | None, explicit_budget: int | None
    ) -> int | None:
        cli_value = os.environ.get("THINKING_BUDGET")
        if cli_value is not None:
            # Intentionally silent: If env var is not a valid integer, fall back to next priority
            with suppress(ValueError):
                return int(cli_value)

        if explicit_budget is not None:
            return explicit_budget

        if reasoning_effort is None:
            return None

        effort_to_budget: dict[str, int] = {
            "low": 512,
            "medium": 2048,
            "high": -1,
        }

        return effort_to_budget.get(reasoning_effort.lower(), None)

    anthropic_thinking = None
    if request.extra_body and isinstance(request.extra_body, dict):
        anthropic_thinking = request.extra_body.get("thinking")

    explicit_budget = getattr(request, "thinking_budget", None)
    if (
        anthropic_thinking
        and isinstance(anthropic_thinking, dict)
        and anthropic_thinking.get("type") == "enabled"
    ):
        explicit_budget = anthropic_thinking.get("budget_tokens") or explicit_budget

    thinking_budget = _resolve_thinking_budget(
        request.reasoning_effort, explicit_budget
    )
    if thinking_budget is not None:
        config["thinkingConfig"] = {
            "thinkingBudget": thinking_budget,
            "includeThoughts": True,
        }

    contents: list[dict[str, Any]] = []
    tool_name_by_id: dict[str, str] = {}

    i = 0
    while i < len(request.messages):
        message = request.messages[i]

        if message.role == "assistant":
            gemini_role = "model"
        elif message.role == "tool":
            gemini_role = "user"
        else:
            gemini_role = message.role
        msg_dict: dict[str, Any] = {"role": gemini_role}
        parts: list[dict[str, Any]] = []

        has_tool_calls = message.role == "assistant" and getattr(
            message, "tool_calls", None
        )
        if has_tool_calls:
            try:
                for tc in message.tool_calls or []:
                    # OPTIMIZATION: Extract attributes directly to avoid expensive model_dump()
                    fn = ""
                    args_raw = ""
                    tc_id = None
                    extra_content = None

                    if isinstance(tc, dict):
                        tc_dict = tc
                        fn = (tc_dict.get("function") or {}).get("name", "")
                        args_raw = (tc_dict.get("function") or {}).get("arguments", "")
                        tc_id = tc_dict.get("id")
                        extra_content = tc_dict.get("extra_content")
                    else:
                        # Fast path for Pydantic models
                        function = getattr(tc, "function", None)
                        if function:
                            if isinstance(function, dict):
                                fn = function.get("name", "")
                                args_raw = function.get("arguments", "")
                            else:
                                fn = getattr(function, "name", "")
                                args_raw = getattr(function, "arguments", "")

                        tc_id = getattr(tc, "id", None)
                        extra_content = getattr(tc, "extra_content", None)

                    if tc_id:
                        tool_name_by_id[tc_id] = fn
                    import json as _json

                    try:
                        args_val = (
                            _json.loads(args_raw)
                            if isinstance(args_raw, str)
                            else args_raw
                        )
                    except (ValueError, TypeError) as err:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "Failed to parse tool arguments JSON, using raw value: %s, error: %s",
                                fn,
                                err,
                                exc_info=True,
                            )
                        args_val = args_raw

                    function_call_part: dict[str, Any] = {
                        "functionCall": {"name": fn, "args": args_val}
                    }

                    if tc_id:
                        function_call_part["functionCall"]["id"] = tc_id

                    if isinstance(extra_content, dict):
                        google_extra = extra_content.get("google", {})
                        thought_sig = google_extra.get("thought_signature")
                        if thought_sig:
                            function_call_part["thoughtSignature"] = thought_sig

                    parts.append(function_call_part)
            except (ValueError, TypeError, KeyError, AttributeError) as err:
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Failed to process tool calls for message, skipping: %s, error: %s",
                        msg_dict.get("role", "unknown"),
                        err,
                        exc_info=True,
                    )

        if message.role != "tool":
            # Include reasoning content if present (e.g. from thinking models)
            if message.reasoning_content:
                parts.append({"text": message.reasoning_content})

            if isinstance(message.content, str):
                if message.content:
                    parts.append({"text": message.content})
            elif isinstance(message.content, list):
                for part in message.content:
                    if hasattr(part, "type") and part.type == "image_url":
                        processed_image = media_utils._process_gemini_image_part(part)
                        if processed_image:
                            parts.append(processed_image)
                    elif hasattr(part, "type") and part.type == "text":
                        from src.core.domain.chat import MessageContentPartText

                        if isinstance(part, MessageContentPartText) and hasattr(
                            part, "text"
                        ):
                            parts.append({"text": part.text})
                    else:
                        if hasattr(part, "model_dump"):
                            part_dict = part.model_dump()
                            if "text" in part_dict:
                                parts.append({"text": part_dict["text"]})

        if message.role == "tool":
            tool_messages = [message]
            j = i + 1
            while j < len(request.messages) and request.messages[j].role == "tool":
                tool_messages.append(request.messages[j])
                j += 1

            for tool_msg in tool_messages:
                tool_call_id = getattr(tool_msg, "tool_call_id", "") or ""
                name = tool_name_by_id.get(tool_call_id, "")
                if not name:
                    name = getattr(tool_msg, "name", "") or ""
                if not name and tool_call_id:
                    name = "function_response"

                import logging as _logging

                _logger = _logging.getLogger(__name__)
                if _logger.isEnabledFor(TRACE_LEVEL):
                    _logger.log(
                        TRACE_LEVEL,
                        "Tool result translation: tool_call_id=%s, "
                        "resolved_name=%s, available_mappings=%s",
                        tool_call_id,
                        name,
                        list(tool_name_by_id.keys()),
                    )

                resp_obj: dict[str, Any]
                val = tool_msg.content
                if isinstance(val, str):
                    import json as _json

                    try:
                        parsed = _json.loads(val)
                        # Gemini API requires function_response.response to be an object.
                        # If the parsed JSON is a list or other non-dict, wrap it.
                        if isinstance(parsed, dict):
                            resp_obj = parsed
                        else:
                            resp_obj = {"result": parsed}
                    except (ValueError, TypeError) as err:
                        if _logger.isEnabledFor(TRACE_LEVEL):
                            _logger.log(
                                TRACE_LEVEL,
                                "Failed to parse tool response JSON, using text fallback: tool_call_id=%s, tool_name=%s, error: %s",
                                tool_call_id,
                                name,
                                err,
                                exc_info=True,
                            )
                        resp_obj = {"text": val}
                elif isinstance(val, dict):
                    resp_obj = val
                elif isinstance(val, list):
                    # Wrap list in an object - Gemini API requires response to be an object
                    resp_obj = {"result": val}
                else:
                    resp_obj = {"text": str(val)}

                function_response = {"name": name, "response": resp_obj}
                if tool_call_id:
                    function_response["id"] = tool_call_id

                parts.append({"functionResponse": function_response})

            i = j - 1

        msg_dict["parts"] = parts  # type: ignore[assignment]

        if parts:
            contents.append(msg_dict)

        i += 1

    result: dict[str, Any] = {"contents": contents, "generationConfig": config}

    if request.tools:
        function_declarations: list[dict[str, Any]] = []

        for tool in request.tools:
            if isinstance(tool, dict):
                tool_dict = tool
            else:
                try:
                    tool_dict = tool.model_dump()  # type: ignore[attr-defined]
                except (AttributeError, TypeError) as err:
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "Failed to serialize tool with model_dump(), using empty dict: type=%s, error: %s",
                            type(tool).__name__,
                            err,
                            exc_info=True,
                        )
                    tool_dict = {}
            function = (
                tool_dict.get("function") if isinstance(tool_dict, dict) else None
            )
            if not function:
                continue

            params = sanitize_gemini_parameters(function.get("parameters", {}))
            function_declarations.append(
                {
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": params,
                }
            )

        if function_declarations:
            result["tools"] = [{"function_declarations": function_declarations}]

    if request.tool_choice:
        mode = "AUTO"
        allowed_functions = None

        if isinstance(request.tool_choice, str):
            if request.tool_choice == "none":
                mode = "NONE"
            elif request.tool_choice == "auto":
                mode = "AUTO"
            elif request.tool_choice in ["any", "required"]:
                mode = "ANY"
        elif (
            isinstance(request.tool_choice, dict)
            and request.tool_choice.get("type") == "function"
        ):
            function_spec = request.tool_choice.get("function", {})
            function_name = function_spec.get("name")
            if function_name:
                mode = "ANY"
                allowed_functions = [function_name]

        fcc: dict[str, Any] = {"mode": mode}
        if allowed_functions:
            fcc["allowedFunctionNames"] = allowed_functions
        result["toolConfig"] = {"functionCallingConfig": fcc}

    response_format = request.response_format
    if not response_format and request.extra_body:
        response_format = request.extra_body.get("response_format")

    if (
        response_format
        and isinstance(response_format, dict)
        and response_format.get("type") == "json_schema"
    ):
        json_schema = response_format.get("json_schema", {})
        schema = json_schema.get("schema", {})

        generation_config = result["generationConfig"]
        if isinstance(generation_config, dict):
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = schema

            schema_name = json_schema.get("name")
            schema_description = json_schema.get("description")
            if schema_name or schema_description:
                schema_context = "Generate a JSON response"
                if schema_name:
                    schema_context += f" for '{schema_name}'"
                if schema_description:
                    schema_context += f": {schema_description}"
                schema_context += (
                    ". The response must conform to the provided JSON schema."
                )

                if (
                    contents
                    and isinstance(contents[-1], dict)
                    and contents[-1].get("role") == "user"
                ):
                    last_message = contents[-1]
                    if (
                        isinstance(last_message, dict)
                        and last_message.get("parts")
                        and isinstance(last_message["parts"], list)
                    ):
                        last_message["parts"].append({"text": f"\n\n{schema_context}"})
                else:
                    contents.append(
                        {"role": "user", "parts": [{"text": schema_context}]}
                    )

    if request.extra_body and isinstance(request.extra_body, dict):
        gemini_safety = request.extra_body.get("gemini_safety_settings")
        if gemini_safety and isinstance(gemini_safety, list):
            result["safetySettings"] = gemini_safety

        cached_content = request.extra_body.get("gemini_cached_content")
        if cached_content:
            result["cachedContent"] = cached_content

    if "tools" in result and logger.isEnabledFor(logging.DEBUG):
        logger.debug("Translation produced tools: %s", str(result["tools"])[:500])

    return result


def _validate_request_parameters(request: CanonicalChatRequest) -> None:
    if not request.model:
        raise ValueError("Model is required")

    if not request.messages:
        raise ValueError("Messages are required")

    for message in request.messages:
        if not message.role:
            raise ValueError("Message role is required")

        if message.role != "system":
            has_text = bool(message.content)
            has_tool_calls = bool(getattr(message, "tool_calls", None))
            if message.role == "assistant":
                # allow empty assistant messages; filtered later
                continue
            if message.role == "tool":
                # allow empty tool messages; handled by translator
                continue
            if not has_text and not has_tool_calls:
                raise ValueError(f"Content is required for {message.role} messages")

    if request.tools:
        for tool in request.tools:
            if isinstance(tool, dict):
                if "function" not in tool:
                    raise ValueError("Tool must have a function")
                if "name" not in tool.get("function", {}):
                    raise ValueError("Tool function must have a name")


def _normalize_stop_sequences(stop: Any) -> list[str] | None:
    if stop is None:
        return None
    if isinstance(stop, str):
        return [stop]
    if isinstance(stop, list):
        return [str(s) for s in stop]
    return [str(stop)]
