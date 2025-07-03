from __future__ import annotations

import logging
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
from typing import Any, Dict, Union

# Moved imports to the top (E402 fix)
import httpx  # json is used for logging, will keep
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from src import models
from src.agents import detect_agent, wrap_proxy_message, format_command_response_for_agent
from src.command_parser import CommandParser
from src.connectors import GeminiBackend, OpenRouterBackend
from src.core.config import _keys_for, _load_config, get_openrouter_headers
from src.core.metadata import _load_project_metadata
from src.core.persistence import ConfigManager
from src.proxy_logic import ProxyState
from src.rate_limit import RateLimitRegistry, parse_retry_delay
from src.security import APIKeyRedactor
from src.session import SessionInteraction, SessionManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def build_app(
    cfg: Dict[str, Any] | None = None, *, config_file: str | None = None
) -> FastAPI:
    cfg = cfg or _load_config()

    disable_auth = cfg.get("disable_auth", False)
    api_key = os.getenv("LLM_INTERACTIVE_PROXY_API_KEY")
    if not disable_auth:
        if not api_key:
            api_key = secrets.token_urlsafe(32)
            logger.warning(
                "No client API key provided, generated one: %s",
                api_key)
            if not any(isinstance(h, logging.StreamHandler)
                       for h in logger.handlers):
                sys.stdout.write(f"Generated client API key: {api_key}\n")
    else:
        api_key = api_key or None

    project_name, project_version = _load_project_metadata()

    functional: set[str] = set()
    # app_for_banner is a reference to the app instance being built.
    # It will be assigned later in this function. This is for _welcome_banner's closure.
    # To make it clearer, we'll pass app_instance to _welcome_banner when it's called.
    # However, _welcome_banner is defined before app_instance is created.
    # This means _welcome_banner must rely on the global 'app' if not passed explicitly,
    # or be defined later, or take 'app' as an argument.
    # For now, let's assume the global 'app' (created at the end of the module) is implicitly used
    # by _welcome_banner if it's not shadowed.
    # The cleanest is to pass app to _welcome_banner.

    def _welcome_banner(current_app: FastAPI, session_id: str) -> str:
        project_name = current_app.state.project_metadata["name"]
        project_version = current_app.state.project_metadata["version"]
        backend_info = []
        # Use current_app.state.functional_backends instead of 'functional'
        # from closure
        if "openrouter" in current_app.state.functional_backends:
            keys = len(cfg.get("openrouter_api_keys", {}))
            models_list = current_app.state.openrouter_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"openrouter (K:{keys}, M:{models_count})")
        if "gemini" in current_app.state.functional_backends:
            keys = len(cfg.get("gemini_api_keys", {}))
            # Ensure gemini_backend is accessed via current_app.state
            models_list = current_app.state.gemini_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"gemini (K:{keys}, M:{models_count})")
        backends_str = ", ".join(sorted(backend_info))
        banner_lines = [
            f"Hello, this is {project_name} {project_version}",
            f"Session id: {session_id}",
            f"Functional backends: {backends_str}",
            f"Type {cfg['command_prefix']}help for list of available commands"
        ]
        return "\n".join(banner_lines)

    @asynccontextmanager
    # Renamed 'app' to 'app_param' to avoid confusion
    async def lifespan(app_param: FastAPI):
        nonlocal functional

        client_httpx = httpx.AsyncClient(timeout=cfg["proxy_timeout"])
        app_param.state.httpx_client = client_httpx
        app_param.state.failover_routes = {}
        default_mode = (
            False
            if cfg.get("disable_interactive_commands")
            else cfg["interactive_mode"]
        )
        app_param.state.session_manager = SessionManager(
            default_interactive_mode=default_mode,
            failover_routes=app_param.state.failover_routes,
        )
        app_param.state.disable_interactive_commands = cfg.get(
            "disable_interactive_commands", False
        )
        app_param.state.command_prefix = cfg["command_prefix"]

        openrouter_backend = OpenRouterBackend(client_httpx)
        gemini_backend = GeminiBackend(client_httpx)
        app_param.state.openrouter_backend = openrouter_backend
        app_param.state.gemini_backend = gemini_backend

        openrouter_ok = False
        gemini_ok = False

        if cfg.get("openrouter_api_keys"):
            openrouter_api_keys_list = list(cfg["openrouter_api_keys"].items())
            if openrouter_api_keys_list:
                key_name, current_api_key = openrouter_api_keys_list[0]
                await openrouter_backend.initialize(
                    openrouter_api_base_url=cfg["openrouter_api_base_url"],
                    openrouter_headers_provider=(
                        lambda n, k: get_openrouter_headers(cfg, k)
                    ),
                    key_name=key_name,
                    api_key=current_api_key,
                )
                if openrouter_backend.get_available_models():
                    openrouter_ok = True

        if cfg.get("gemini_api_keys"):
            gemini_api_keys_list = list(cfg["gemini_api_keys"].items())
            if gemini_api_keys_list:
                key_name, current_api_key = gemini_api_keys_list[0]
                await gemini_backend.initialize(
                    gemini_api_base_url=cfg["gemini_api_base_url"],
                    key_name=key_name,
                    api_key=current_api_key,
                )
                if gemini_backend.get_available_models():
                    gemini_ok = True

        functional = {
            name
            for name, ok in (("openrouter", openrouter_ok), ("gemini", gemini_ok))
            if ok
        }
        app_param.state.functional_backends = functional

        backend_type = cfg.get("backend")
        if backend_type:
            if functional and backend_type not in functional:
                raise ValueError(
                    f"default backend {backend_type} is not functional"
                )
        else:
            if len(functional) == 1:
                backend_type = next(iter(functional))
            elif len(functional) > 1:
                # E501: Wrapped string
                raise ValueError(
                    "Multiple functional backends, specify --default-backend"
                )
            else:
                backend_type = "openrouter"
        app_param.state.backend_type = backend_type
        app_param.state.initial_backend_type = backend_type

        current_backend = (
            gemini_backend if backend_type == "gemini" else openrouter_backend
        )
        app_param.state.backend = current_backend

        all_keys = list(cfg.get("openrouter_api_keys", {}).values()) + list(
            cfg.get("gemini_api_keys", {}).values()
        )
        app_param.state.api_key_redactor = APIKeyRedactor(all_keys)
        app_param.state.default_api_key_redaction_enabled = cfg.get(
            "redact_api_keys_in_prompts", True
        )
        app_param.state.api_key_redaction_enabled = (
            app_param.state.default_api_key_redaction_enabled
        )
        app_param.state.rate_limits = RateLimitRegistry()
        app_param.state.force_set_project = cfg.get("force_set_project", False)

        if config_file:
            app_param.state.config_manager = ConfigManager(
                app_param, config_file)
            app_param.state.config_manager.load()
        else:
            app_param.state.config_manager = None

        yield
        await client_httpx.aclose()

    app_instance = FastAPI(lifespan=lifespan)
    app_instance.state.project_metadata = {
        "name": project_name, "version": project_version}
    app_instance.state.client_api_key = api_key
    app_instance.state.disable_auth = disable_auth

    async def verify_client_auth(http_request: Request) -> None:
        if http_request.app.state.disable_auth:
            return
        auth_header = http_request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = auth_header.split(" ", 1)[1]
        if token != http_request.app.state.client_api_key:
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app_instance.get("/")
    async def root():
        return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

    @app_instance.post(
        "/v1/chat/completions",
        response_model=Union[
            models.CommandProcessedChatCompletionResponse, Dict[str, Any]
        ],
        dependencies=[Depends(verify_client_auth)],
    )
    async def chat_completions(
        request_data: models.ChatCompletionRequest, http_request: Request
    ):
        session_id = http_request.headers.get("x-session-id", "default")
        session = http_request.app.state.session_manager.get_session(
            session_id)
        proxy_state: ProxyState = session.proxy_state

        if session.agent is None and request_data.messages:
            first = request_data.messages[0]
            if isinstance(first.content, str):
                text = first.content
            elif isinstance(first.content, list):
                # E501: Wrapped list comprehension
                text = " ".join(
                    p.text for p in first.content
                    if isinstance(p, models.MessageContentPartText)
                )
            else:
                text = ""
            session.agent = detect_agent(text)

        current_backend_type = http_request.app.state.backend_type
        if proxy_state.override_backend:
            current_backend_type = proxy_state.override_backend
            if proxy_state.invalid_override:
                # E501: Wrapped detail message
                detail_msg = {
                    "message": "invalid or unsupported model",
                    "model": (
                        f"{proxy_state.override_backend}:"
                        f"{proxy_state.override_model}"
                    ),
                }
                raise HTTPException(status_code=400, detail=detail_msg)
            if current_backend_type not in {"openrouter", "gemini"}:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown backend {current_backend_type}")

        parser = None
        if not http_request.app.state.disable_interactive_commands:
            parser = CommandParser(
                proxy_state,
                http_request.app,
                command_prefix=http_request.app.state.command_prefix,
                preserve_unknown=not proxy_state.interactive_mode,
                functional_backends=http_request.app.state.functional_backends,
            )
            processed_messages, commands_processed = parser.process_messages(
                request_data.messages
            )
            if parser.command_results and any(
                    not result.success for result in parser.command_results):
                error_messages = [
                    result.message for result in parser.command_results if not result.success]
                # E501: Wrapped dict
                return {
                    "id": "proxy_cmd_processed",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request_data.model,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "; ".join(error_messages),
                        },
                        "finish_reason": "error",
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                }
        else:
            processed_messages = request_data.messages
            commands_processed = False

        if proxy_state.override_backend:
            current_backend_type = proxy_state.override_backend
        else:
            current_backend_type = http_request.app.state.backend_type

        show_banner = False
        if proxy_state.interactive_mode:
            if not session.history:
                show_banner = True
            if proxy_state.interactive_just_enabled:
                show_banner = True
            if proxy_state.hello_requested:
                show_banner = True

        raw_prompt = ""
        if request_data.messages:
            last_msg = request_data.messages[-1]
            if isinstance(last_msg.content, str):
                raw_prompt = last_msg.content
            elif isinstance(last_msg.content, list):
                raw_prompt = " ".join(
                    part.text
                    for part in last_msg.content
                    if isinstance(part, models.MessageContentPartText)
                )

        if commands_processed:
            if not processed_messages:
                pass
            else:
                last_msg = processed_messages[-1]
                # The following lines were causing a Pylance warning "Expression value is unused".
                # They were evaluating a boolean expression but not using the result.
                # Removed them as they were effectively no-ops.
                # if isinstance(last_msg.content, str):
                #     not last_msg.content.strip()
                # elif isinstance(last_msg.content, list):
                #     # E501: Wrapped comprehension
                #     not any(
                #         part.text.strip() for part in last_msg.content
                #         if isinstance(part, models.MessageContentPartText)
                #     )

        confirmation_text = ""
        if parser is not None:
            confirmation_text = "\n".join(
                r.message for r in parser.command_results if r.message
            )

        if commands_processed:
            content_lines_for_agent = []
            if proxy_state.interactive_mode and show_banner:
                banner_content = _welcome_banner(http_request.app, session_id)
                content_lines_for_agent.extend(banner_content.splitlines())
            elif show_banner:  # This condition might need review, but keeping its logic.
                banner_content = _welcome_banner(http_request.app, session_id)
                content_lines_for_agent.extend(banner_content.splitlines())

            if confirmation_text:
                content_lines_for_agent.extend(confirmation_text.splitlines())

            if not content_lines_for_agent:
                content_lines_for_agent = [
                    "Proxy command processed. No query sent to LLM."]

            formatted_agent_response = format_command_response_for_agent(
                content_lines_for_agent, session.agent)
            response_text = wrap_proxy_message(
                session.agent, formatted_agent_response)

            # The rest of the block (session.add_interaction, return models.CommandProcessedChatCompletionResponse)
            # uses this final response_text.
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="proxy",
                    model=proxy_state.get_effective_model(request_data.model),
                    project=proxy_state.project,
                    response=response_text,
                )
            )
            proxy_state.hello_requested = False
            proxy_state.interactive_just_enabled = False
            return models.CommandProcessedChatCompletionResponse(
                id="proxy_cmd_processed",
                object="chat.completion",
                created=int(datetime.now(timezone.utc).timestamp()),
                model=proxy_state.get_effective_model(request_data.model),
                choices=[models.ChatCompletionChoice(
                    index=0,
                    message=models.ChatCompletionChoiceMessage(
                        role="assistant", content=response_text,
                    ),
                    finish_reason="stop",
                )],
                usage=models.CompletionUsage(
                    prompt_tokens=0, completion_tokens=0, total_tokens=0
                ),
            )

        if not processed_messages:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No messages provided in the request or messages became "
                    "empty after processing."
                ),
            )

        if http_request.app.state.force_set_project and proxy_state.project is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Project name not set. Use !/set(project=<name>) before "
                    "sending prompts."
                ),
            )

        effective_model = proxy_state.get_effective_model(request_data.model)

        async def _call_backend(
            b_type: str, model_str: str, key_name_str: str, api_key_str: str
        ):
            if b_type == "gemini":
                retry_at = http_request.app.state.rate_limits.get(
                    "gemini", model_str, key_name_str
                )
                if retry_at:
                    # E501: Wrapped dict
                    detail_dict = {
                        "message": "Backend rate limited, retry later",
                        "retry_after": int(retry_at - time.time()),
                    }
                    raise HTTPException(status_code=429, detail=detail_dict)
                try:
                    result = (
                        await http_request.app.state.gemini_backend.chat_completions(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            project=proxy_state.project,
                            gemini_api_base_url=cfg["gemini_api_base_url"],
                            key_name=key_name_str,
                            api_key=api_key_str,
                            prompt_redactor=(
                                http_request.app.state.api_key_redactor
                                if http_request.app.state.api_key_redaction_enabled
                                else None
                            ),
                        )
                    )
                    logger.debug(
                        f"Result from Gemini backend chat_completions: {result}"
                    )
                    return result
                except HTTPException as e:
                    if e.status_code == 429:
                        delay = parse_retry_delay(e.detail)
                        if delay:
                            http_request.app.state.rate_limits.set(
                                "gemini", model_str, key_name_str, delay
                            )
                    raise

            retry_at = http_request.app.state.rate_limits.get(
                "openrouter", model_str, key_name_str
            )
            if retry_at:
                detail_dict = {  # E501
                    "message": "Backend rate limited, retry later",
                    "retry_after": int(retry_at - time.time()),
                }
                raise HTTPException(status_code=429, detail=detail_dict)
            try:
                result = (
                    await http_request.app.state.openrouter_backend.chat_completions(
                        request_data=request_data,
                        processed_messages=processed_messages,
                        effective_model=model_str,
                        openrouter_api_base_url=cfg["openrouter_api_base_url"],
                        openrouter_headers_provider=(
                            lambda n, k: get_openrouter_headers(cfg, k)
                        ),
                        key_name=key_name_str,
                        api_key=api_key_str,
                        project=proxy_state.project,
                        prompt_redactor=(
                            http_request.app.state.api_key_redactor
                            if http_request.app.state.api_key_redaction_enabled
                            else None
                        ),
                    )
                )
                logger.debug(
                    f"Result from OpenRouter backend chat_completions: {result}"
                )
                return result
            except HTTPException as e:
                if e.status_code == 429:
                    delay = parse_retry_delay(e.detail)
                    if delay:
                        http_request.app.state.rate_limits.set(
                            "openrouter", model_str, key_name_str, delay
                        )
                raise

        route = proxy_state.failover_routes.get(effective_model)
        attempts: list[tuple[str, str, str, str]] = []
        if route:
            elements = route.get("elements", [])
            if isinstance(elements, dict):
                elems = list(elements.values())
            elif isinstance(elements, list):
                elems = elements
            else:
                elems = []
            policy = route.get("policy", "k")
            if policy == "k" and elems:
                b, m = elems[0].split(":", 1)
                for kname, key_val in _keys_for(cfg, b):
                    attempts.append((b, m, kname, key_val))
            elif policy == "m":
                for el in elems:
                    b, m = el.split(":", 1)
                    keys = _keys_for(cfg, b)
                    if not keys:
                        continue
                    kname, key_val = keys[0]
                    attempts.append((b, m, kname, key_val))
            elif policy == "km":
                for el in elems:
                    b, m = el.split(":", 1)
                    for kname, key_val in _keys_for(cfg, b):
                        attempts.append((b, m, kname, key_val))
            elif policy == "mk":
                backends_used = {el.split(":", 1)[0] for el in elems}
                key_map = {b: _keys_for(cfg, b) for b in backends_used}
                max_len = max(len(v)
                              for v in key_map.values()) if key_map else 0
                for i in range(max_len):
                    for el in elems:
                        b, m = el.split(":", 1)
                        if i < len(key_map[b]):
                            kname, key_val = key_map[b][i]
                            attempts.append((b, m, kname, key_val))
        else:
            default_keys = _keys_for(cfg, current_backend_type)
            if not default_keys:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"No API keys configured for the default backend: "
                        f"{current_backend_type}"
                    ),
                )
            attempts.append(
                (
                    current_backend_type,
                    effective_model,
                    default_keys[0][0],
                    default_keys[0][1],
                )
            )

        while True:
            last_error: HTTPException | None = None
            response_from_backend = None
            used_backend = current_backend_type
            used_model = effective_model
            success = False
            earliest_retry: float | None = None
            for b_attempt, m_attempt, kname_attempt, key_attempt in attempts:
                logger.debug(
                    f"Attempting backend: {b_attempt}, model: {m_attempt}, "
                    f"key_name: {kname_attempt}"
                )
                try:
                    response_from_backend = await _call_backend(
                        b_attempt, m_attempt, kname_attempt, key_attempt
                    )
                    used_backend = b_attempt
                    used_model = m_attempt
                    success = True
                    logger.debug(
                        f"Attempt successful for backend: {b_attempt}, model: {m_attempt}, "
                        f"key_name: {kname_attempt}")
                    break
                except HTTPException as e:
                    logger.debug(
                        f"Attempt failed for backend: {b_attempt}, model: {m_attempt}, "
                        f"key_name: {kname_attempt} with HTTPException: {e.status_code} "
                        f"- {e.detail}")
                    if e.status_code == 429:
                        last_error = e
                        retry_ts = http_request.app.state.rate_limits.get(
                            b_attempt, m_attempt, kname_attempt
                        )
                        if retry_ts and (
                            earliest_retry is None or retry_ts < earliest_retry
                        ):
                            earliest_retry = retry_ts
                        continue
                    raise
            if success:
                break

            if last_error and last_error.status_code == 429:
                if earliest_retry is None:
                    earliest_retry = http_request.app.state.rate_limits.next_available()
                if earliest_retry:
                    wait_time = max(0.0, earliest_retry - time.time())
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                    continue

            error_msg_detail = last_error.detail if last_error else "all backends failed"
            status_code_to_return = last_error.status_code if last_error else 500
            response_content = {
                "id": "error",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"All backends failed: {error_msg_detail}",
                        },
                        "finish_reason": "error",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "error": error_msg_detail,
            }
            raise HTTPException(
                status_code=status_code_to_return, detail=response_content
            )

        if isinstance(response_from_backend, StreamingResponse):
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt, handler="backend", backend=used_backend,
                    model=used_model, project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response="<streaming>",
                )
            )
            return response_from_backend

        backend_response_dict: Dict[str, Any] = response_from_backend if isinstance(
            response_from_backend, dict) else {}

        if "choices" not in backend_response_dict:
            backend_response_dict["choices"] = [{"index": 0, "message": {
                "role": "assistant", "content": "(no response)"}, "finish_reason": "error"}]

        if proxy_state.interactive_mode:
            prefix_parts = []
            if show_banner:
                prefix_parts.append(
                    _welcome_banner(
                        http_request.app,
                        session_id))
            if confirmation_text:
                prefix_parts.append(confirmation_text)
            if prefix_parts:
                prefix_text_str = wrap_proxy_message(
                    session.agent, "\n".join(prefix_parts))
                orig_content = (
                    backend_response_dict.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                # E501: Wrapped assignment
                backend_response_dict["choices"][0]["message"]["content"] = (
                    f"{prefix_text_str}\n{orig_content}" if orig_content
                    else prefix_text_str
                )

        usage_data = backend_response_dict.get("usage")
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt, handler="backend", backend=used_backend,
                model=used_model, project=proxy_state.project,
                parameters=request_data.model_dump(exclude_unset=True),
                response=backend_response_dict.get("choices", [{}])[0]
                .get("message", {}).get("content"),
                usage=(
                    models.CompletionUsage(**usage_data)
                    if isinstance(usage_data, dict) else None
                ),
            )
        )
        proxy_state.hello_requested = False
        proxy_state.interactive_just_enabled = False
        return backend_response_dict

    @app_instance.get("/models", dependencies=[Depends(verify_client_auth)])
    async def list_all_models(http_request: Request):
        data = []
        if "openrouter" in http_request.app.state.functional_backends:
            for m in http_request.app.state.openrouter_backend.get_available_models():
                data.append({"id": f"openrouter:{m}"})
        if "gemini" in http_request.app.state.functional_backends:
            for m in http_request.app.state.gemini_backend.get_available_models():
                data.append({"id": f"gemini:{m}"})
        return {"object": "list", "data": data}

    @app_instance.get("/v1/models", dependencies=[Depends(verify_client_auth)])
    async def list_models(http_request: Request):
        data = []
        if "openrouter" in http_request.app.state.functional_backends:
            for m in http_request.app.state.openrouter_backend.get_available_models():
                data.append({"id": f"openrouter:{m}"})
        if "gemini" in http_request.app.state.functional_backends:
            for m in http_request.app.state.gemini_backend.get_available_models():
                data.append({"id": f"gemini:{m}"})
        return {"object": "list", "data": data}

    return app_instance

if __name__ == "__main__":
    from src.core.cli import main as cli_main
    cli_main(build_app_fn=build_app)
