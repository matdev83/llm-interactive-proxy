"""Project Responses domain requests to Gemini generateContent-style payloads."""

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
from src.core.domain.translators.gemini.schema import sanitize_gemini_parameters
from src.core.interfaces.responses_projector import IResponsesBackendProjector

_PROVIDER = "gemini"

_ALLOWED_EXTRA_BODY_KEYS = frozenset(
    {"gemini_safety_settings", "gemini_cached_content"}
)

_UNSUPPORTED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "conversation",
        "include",
        "prompt",
        "prompt_cache_key",
        "prompt_cache_retention",
        "truncation",
        "store",
        "stream_options",
        "logit_bias",
        "parallel_tool_calls",
        "background",
        "session_id",
        "agent",
        "safety_identifier",
        "text",
        "reasoning",
        "max_tool_calls",
        "service_tier",
        "metadata",
        "user",
    }
)


def _parse_json_value(raw: str | None) -> Any:
    if raw is None or raw.strip() == "":
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _function_response_object(output: str | None) -> dict[str, Any]:
    if output is None or output.strip() == "":
        return {}
    try:
        parsed: Any = json.loads(output)
    except json.JSONDecodeError:
        return {"text": output}
    if isinstance(parsed, dict):
        return parsed
    return {"result": parsed}


def _tools_openai_to_gemini(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    function_declarations: list[dict[str, Any]] = []
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
            "parameters": sanitize_gemini_parameters(parameters),
        }
        if isinstance(description, str) and description:
            entry["description"] = description
        function_declarations.append(entry)
    return [{"function_declarations": function_declarations}]


def _message_parts_from_content(
    parts: list[ResponsesContentPart] | str | None,
) -> list[dict[str, Any]]:
    if parts is None:
        return []
    if isinstance(parts, str):
        return [{"text": parts}] if parts else []
    out: list[dict[str, Any]] = []
    for part in parts:
        if part.type in ("input_text", "output_text", "text"):
            if part.text is not None:
                out.append({"text": part.text})
        elif part.type == "input_image" or part.image_url is not None:
            raise ResponsesProviderLimitationError("content_part.image", _PROVIDER)
        else:
            raise ResponsesProviderLimitationError(
                f"content_part.{part.type}", _PROVIDER
            )
    return out


def _model_parts_conflict(parts: list[dict[str, Any]]) -> bool:
    has_fc = any("functionCall" in p for p in parts)
    has_text = any("text" in p for p in parts)
    return has_fc and has_text


def _emit_model(contents: list[dict[str, Any]], pending: list[dict[str, Any]]) -> None:
    if not pending:
        return
    if _model_parts_conflict(pending):
        raise ResponsesProviderLimitationError(
            "model.functionCall_with_text", _PROVIDER
        )
    contents.append({"role": "model", "parts": list(pending)})
    pending.clear()


def _emit_user(contents: list[dict[str, Any]], pending: list[dict[str, Any]]) -> None:
    if not pending:
        return
    contents.append({"role": "user", "parts": list(pending)})
    pending.clear()


def _function_call_part(
    item: ResponsesInputItem | ResponsesOutputItem,
    call_id_to_name: dict[str, str],
) -> dict[str, Any]:
    name = item.name or ""
    call_id = item.call_id or ""
    if call_id:
        call_id_to_name[str(call_id)] = str(name)
    raw_args: str | None
    raw_args = item.arguments if isinstance(item.arguments, str) else None
    args_val = _parse_json_value(raw_args) if raw_args is not None else {}
    fc: dict[str, Any] = {"name": str(name), "args": args_val}
    if call_id:
        fc["id"] = str(call_id)
    return {"functionCall": fc}


def _function_response_part(
    call_id: str,
    name: str,
    output: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "response": _function_response_object(output),
    }
    if call_id:
        body["id"] = str(call_id)
    return {"functionResponse": body}


def _convert_input_items(
    items: list[ResponsesInputItem],
) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    pending_model: list[dict[str, Any]] = []
    pending_user: list[dict[str, Any]] = []
    call_id_to_name: dict[str, str] = {}

    for item in items:
        itype = item.type
        if itype == "message":
            role = item.role or "user"
            if role == "assistant":
                _emit_user(contents, pending_user)
                parts = _message_parts_from_content(item.content)
                pending_model.extend(parts)
            elif role == "user":
                _emit_model(contents, pending_model)
                _emit_user(contents, pending_user)
                parts = _message_parts_from_content(item.content)
                if parts:
                    contents.append({"role": "user", "parts": parts})
            elif role in ("system", "developer"):
                _emit_model(contents, pending_model)
                _emit_user(contents, pending_user)
                prefix = "System" if role == "system" else "Developer"
                if isinstance(item.content, list):
                    texts = [
                        p.text or ""
                        for p in item.content
                        if p.type in ("input_text", "output_text", "text")
                    ]
                    body = "\n".join(t for t in texts if t).strip()
                elif isinstance(item.content, str):
                    body = item.content.strip()
                else:
                    body = ""
                text = f"[{prefix}]\n{body}".strip()
                if text:
                    contents.append({"role": "user", "parts": [{"text": text}]})
            else:
                raise ResponsesProviderLimitationError(
                    f"input_item.message.role={role}", _PROVIDER
                )
        elif itype == "function_call":
            _emit_user(contents, pending_user)
            pending_model.append(_function_call_part(item, call_id_to_name))
        elif itype == "function_call_output":
            _emit_model(contents, pending_model)
            cid = str(item.call_id or "")
            fn_name = (
                (item.name or "").strip()
                or call_id_to_name.get(cid, "").strip()
                or "function_response"
            )
            pending_user.append(_function_response_part(cid, fn_name, item.output))
        else:
            raise ResponsesProviderLimitationError(f"input_item.{itype}", _PROVIDER)

    _emit_model(contents, pending_model)
    _emit_user(contents, pending_user)
    return contents


def _convert_output_item(
    item: ResponsesOutputItem,
    call_id_to_name: dict[str, str],
) -> list[dict[str, Any]]:
    otype = item.type
    if otype == "message":
        role = item.role or "assistant"
        if role == "assistant":
            parts = _message_parts_from_content(item.content)
            if not parts:
                return []
            return [{"role": "model", "parts": parts}]
        if role == "user":
            parts = _message_parts_from_content(item.content)
            if not parts:
                return []
            return [{"role": "user", "parts": parts}]
        raise ResponsesProviderLimitationError(
            f"prior_output_item.message.role={role}", _PROVIDER
        )
    if otype == "function_call":
        return [
            {
                "role": "model",
                "parts": [_function_call_part(item, call_id_to_name)],
            }
        ]
    raise ResponsesProviderLimitationError(f"prior_output_item.{otype}", _PROVIDER)


def _apply_response_format(
    payload: dict[str, Any],
    response_format: dict[str, Any] | None,
) -> None:
    if response_format is None:
        return
    if response_format.get("type") != "json_schema":
        raise ResponsesProviderLimitationError("response_format", _PROVIDER)
    json_schema = response_format.get("json_schema", {})
    if not isinstance(json_schema, dict):
        raise ResponsesProviderLimitationError("response_format.json_schema", _PROVIDER)
    schema = json_schema.get("schema", {})
    if not isinstance(schema, dict):
        raise ResponsesProviderLimitationError(
            "response_format.json_schema.schema", _PROVIDER
        )
    gen = dict(payload.get("generationConfig") or {})
    gen["responseMimeType"] = "application/json"
    gen["responseSchema"] = schema
    payload["generationConfig"] = gen

    schema_name = json_schema.get("name")
    schema_description = json_schema.get("description")
    if schema_name or schema_description:
        schema_context = "Generate a JSON response"
        if schema_name:
            schema_context += f" for '{schema_name}'"
        if schema_description:
            schema_context += f": {schema_description}"
        schema_context += ". The response must conform to the provided JSON schema."
        contents = payload["contents"]
        if contents and contents[-1].get("role") == "user":
            last = contents[-1]
            lp = last.get("parts")
            if isinstance(lp, list):
                lp.append({"text": f"\n\n{schema_context}"})
        else:
            contents.append({"role": "user", "parts": [{"text": schema_context}]})


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

    eb = req.extra_body
    if isinstance(eb, dict) and eb:
        for k in sorted(eb.keys()):
            if k in _ALLOWED_EXTRA_BODY_KEYS:
                continue
            raise ResponsesProviderLimitationError(f"extra_body.{k}", _PROVIDER)


class GeminiResponsesProjector(IResponsesBackendProjector):
    def project(
        self,
        request: ResponsesDomainRequest,
        prior_items: list[ResponsesOutputItem] | None,
    ) -> tuple[dict[str, Any], list[str]]:
        _assert_no_unsupported_request_fields(request)

        call_id_to_name: dict[str, str] = {}
        contents: list[dict[str, Any]] = []
        if prior_items:
            for out in prior_items:
                contents.extend(_convert_output_item(out, call_id_to_name))

        contents.extend(_convert_input_items(list(request.input)))

        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.top_p is not None:
            generation_config["topP"] = request.top_p
        max_out = request.max_output_tokens
        max_tok = request.max_tokens
        if max_out is not None and max_tok is not None and max_out != max_tok:
            raise ResponsesProviderLimitationError(
                "max_tokens_vs_max_output_tokens", _PROVIDER
            )
        if max_out is not None:
            generation_config["maxOutputTokens"] = max_out
        elif max_tok is not None:
            generation_config["maxOutputTokens"] = max_tok

        if request.stop is not None:
            if isinstance(request.stop, str):
                generation_config["stopSequences"] = [request.stop]
            elif isinstance(request.stop, list):
                generation_config["stopSequences"] = [str(s) for s in request.stop]
            else:
                raise ResponsesProviderLimitationError("stop", _PROVIDER)

        if request.seed is not None:
            generation_config["seed"] = request.seed

        if request.presence_penalty is not None:
            generation_config["presencePenalty"] = request.presence_penalty

        if request.frequency_penalty is not None:
            generation_config["frequencyPenalty"] = request.frequency_penalty

        if request.top_logprobs is not None:
            generation_config["logprobs"] = request.top_logprobs

        if request.n is not None and request.n > 1:
            generation_config["candidateCount"] = request.n

        payload: dict[str, Any] = {
            "model": request.model,
            "contents": contents,
            "generationConfig": generation_config,
        }

        if request.instructions is not None and request.instructions != "":
            payload["systemInstruction"] = {
                "parts": [{"text": request.instructions}],
            }

        if request.tools is not None:
            tool_dicts = [t for t in request.tools if isinstance(t, dict)]
            if tool_dicts:
                payload["tools"] = _tools_openai_to_gemini(tool_dicts)

        if request.tool_choice is not None:
            mode = "AUTO"
            allowed_functions: list[str] | None = None
            tc = request.tool_choice
            if isinstance(tc, str):
                if tc == "none":
                    mode = "NONE"
                elif tc == "auto":
                    mode = "AUTO"
                elif tc in ("any", "required"):
                    mode = "ANY"
            elif isinstance(tc, dict) and tc.get("type") == "function":
                fn_spec = tc.get("function", {})
                fn_name = fn_spec.get("name") if isinstance(fn_spec, dict) else None
                if isinstance(fn_name, str) and fn_name:
                    mode = "ANY"
                    allowed_functions = [fn_name]
            fcc: dict[str, Any] = {"mode": mode}
            if allowed_functions:
                fcc["allowedFunctionNames"] = allowed_functions
            payload["toolConfig"] = {"functionCallingConfig": fcc}

        rf = request.response_format
        if rf is None and isinstance(request.extra_body, dict):
            rf = request.extra_body.get("response_format")
        if isinstance(rf, dict):
            _apply_response_format(payload, rf)

        eb = request.extra_body
        if isinstance(eb, dict):
            safety = eb.get("gemini_safety_settings")
            if isinstance(safety, list):
                payload["safetySettings"] = safety
            cached = eb.get("gemini_cached_content")
            if cached:
                payload["cachedContent"] = cached

        return payload, []
