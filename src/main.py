from __future__ import annotations

import json
import logging
import time
import os
import secrets
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse

from src import models
from src.proxy_logic import ProxyState
from src.command_parser import CommandParser
from src.session import SessionManager, SessionInteraction
from src.agents import detect_agent, wrap_proxy_message
from src.connectors import OpenRouterBackend, GeminiBackend
from src.security import APIKeyRedactor
from src.rate_limit import RateLimitRegistry, parse_retry_delay

from src.core.metadata import _load_project_metadata
from src.core.config import _load_config, get_openrouter_headers, _keys_for


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


from src.core.persistence import ConfigManager


def build_app(cfg: Dict[str, Any] | None = None, *, config_file: str | None = None) -> FastAPI:
    cfg = cfg or _load_config()

    disable_auth = cfg.get("disable_auth", False)
    api_key = os.getenv("LLM_INTERACTIVE_PROXY_API_KEY")
    generated_key = False
    if not disable_auth:
        if not api_key:
            api_key = secrets.token_urlsafe(32)
            generated_key = True
            logger.warning(
                "No client API key provided, generated one: %s", api_key
            )
            if not any(
                isinstance(h, logging.StreamHandler) for h in logger.handlers
            ):
                sys.stdout.write(f"Generated client API key: {api_key}\n")
    else:
        api_key = api_key or None

    project_name, project_version = _load_project_metadata()

    functional: set[str] = set()

    def _welcome_banner(session_id: str) -> str:
        backend_info = []
        if "openrouter" in functional:
            keys = len(cfg.get("openrouter_api_keys", {}))
            models = len(app.state.openrouter_backend.get_available_models())
            backend_info.append(f"openrouter (K:{keys}, M:{models})")
        if "gemini" in functional:
            keys = len(cfg.get("gemini_api_keys", {}))
            models = len(app.state.gemini_backend.get_available_models())
            backend_info.append(f"gemini (K:{keys}, M:{models})")
        backends_str = ", ".join(sorted(backend_info))
        return (
            f"<thinking>Hello, this is {project_name} {project_version}\n"
            f"Session id: {session_id}\n"
            f"Functional backends: {backends_str}\n"
            f"Type {cfg['command_prefix']}help for list of available commands</thinking>"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal functional
        client = httpx.AsyncClient(timeout=cfg["proxy_timeout"])
        app.state.httpx_client = client
        app.state.failover_routes = {}
        default_mode = (
            False if cfg.get("disable_interactive_commands") else cfg["interactive_mode"]
        )
        app.state.session_manager = SessionManager(
            default_interactive_mode=default_mode,
            failover_routes=app.state.failover_routes,
        )
        app.state.disable_interactive_commands = cfg.get(
            "disable_interactive_commands", False
        )
        app.state.command_prefix = cfg["command_prefix"]

        openrouter_backend = OpenRouterBackend(client)
        gemini_backend = GeminiBackend(client)
        app.state.openrouter_backend = openrouter_backend
        app.state.gemini_backend = gemini_backend

        openrouter_ok = False
        gemini_ok = False

        if cfg.get("openrouter_api_keys"):
            openrouter_api_keys_list = list(cfg["openrouter_api_keys"].items())
            if openrouter_api_keys_list:
                key_name, api_key = openrouter_api_keys_list[0]
                await openrouter_backend.initialize(
                    openrouter_api_base_url=cfg["openrouter_api_base_url"],
                    openrouter_headers_provider=lambda n, k: get_openrouter_headers(
                        cfg, k
                    ),
                    key_name=key_name,
                    api_key=api_key,
                )
                # Check if models were successfully fetched during initialization
                if openrouter_backend.get_available_models():
                    openrouter_ok = True

        if cfg.get("gemini_api_keys"):
            gemini_api_keys_list = list(cfg["gemini_api_keys"].items())
            if gemini_api_keys_list:
                key_name, api_key = gemini_api_keys_list[0]
                await gemini_backend.initialize(
                    gemini_api_base_url=cfg["gemini_api_base_url"],
                    key_name=key_name,
                    api_key=api_key,
                )
                if gemini_backend.get_available_models():
                    gemini_ok = True

        functional = {
            name
            for name, ok in (("openrouter", openrouter_ok), ("gemini", gemini_ok))
            if ok
        }
        app.state.functional_backends = functional

        backend_type = cfg.get("backend")
        if backend_type:
            if functional and backend_type not in functional:
                raise ValueError(f"default backend {backend_type} is not functional")
        else:
            if len(functional) == 1:
                backend_type = next(iter(functional))
            elif len(functional) > 1:
                raise ValueError(
                    "Multiple functional backends, specify --default-backend"
                )
            else:
                backend_type = "openrouter"
        app.state.backend_type = backend_type
        app.state.initial_backend_type = backend_type

        backend = gemini_backend if backend_type == "gemini" else openrouter_backend
        app.state.backend = backend

        all_keys = list(cfg.get("openrouter_api_keys", {}).values()) + list(
            cfg.get("gemini_api_keys", {}).values()
        )
        app.state.api_key_redactor = APIKeyRedactor(all_keys)
        app.state.default_api_key_redaction_enabled = cfg.get(
            "redact_api_keys_in_prompts", True
        )
        app.state.api_key_redaction_enabled = (
            app.state.default_api_key_redaction_enabled
        )
        app.state.rate_limits = RateLimitRegistry()
        app.state.force_set_project = cfg.get("force_set_project", False)

        if config_file:
            app.state.config_manager = ConfigManager(app, config_file)
            app.state.config_manager.load()
        else:
            app.state.config_manager = None

        # ------------------------------------------------------------------
        yield
        await client.aclose()

    app = FastAPI(lifespan=lifespan)
    app.state.client_api_key = api_key
    app.state.disable_auth = disable_auth

    async def verify_client_auth(http_request: Request) -> None:
        if http_request.app.state.disable_auth:
            return
        auth_header = http_request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = auth_header.split(" ", 1)[1]
        if token != http_request.app.state.client_api_key:
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/")
    async def root():
        return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

    @app.post(
        "/v1/chat/completions",
        response_model=Union[
            models.CommandProcessedChatCompletionResponse, Dict[str, Any]
        ],
        dependencies=[Depends(verify_client_auth)],
    )
    async def chat_completions(
        request_data: models.ChatCompletionRequest, http_request: Request
    ):
        backend_type = http_request.app.state.backend_type
        backend = http_request.app.state.backend
        session_id = http_request.headers.get("x-session-id", "default")
        session = http_request.app.state.session_manager.get_session(session_id)
        proxy_state: ProxyState = session.proxy_state

        if session.agent is None and request_data.messages:
            first = request_data.messages[0]
            if isinstance(first.content, str):
                text = first.content
            elif isinstance(first.content, list):
                text = " ".join(
                    p.text for p in first.content if isinstance(p, models.MessageContentPartText)
                )
            else:
                text = ""
            session.agent = detect_agent(text)

        if proxy_state.override_backend:
            backend_type = proxy_state.override_backend
            if proxy_state.invalid_override:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "invalid or unsupported model",
                        "model": f"{proxy_state.override_backend}:{proxy_state.override_model}",
                    },
                )
            if backend_type == "openrouter":
                backend = http_request.app.state.openrouter_backend
            elif backend_type == "gemini":
                backend = http_request.app.state.gemini_backend
            else:
                raise HTTPException(
                    status_code=400, detail=f"unknown backend {backend_type}"
                )

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
            # Check for command errors and return them if any
            if parser.results and any(not result.success for result in parser.results):
                error_messages = [result.message for result in parser.results if not result.success]
                return {
                    "id": "proxy_cmd_processed",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request_data.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "; ".join(error_messages),
                            },
                            "finish_reason": "error",
                        }
                    ],
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
            backend_type = proxy_state.override_backend
            if backend_type == "openrouter":
                backend = http_request.app.state.openrouter_backend
            elif backend_type == "gemini":
                backend = http_request.app.state.gemini_backend
            else:
                raise HTTPException(
                    status_code=400, detail=f"unknown backend {backend_type}"
                )
        else:
            backend_type = http_request.app.state.backend_type
            if backend_type == "gemini":
                backend = http_request.app.state.gemini_backend
            else:
                backend = http_request.app.state.openrouter_backend
        show_banner = False
        if proxy_state.interactive_mode:
            if not session.history:
                show_banner = True
            if proxy_state.interactive_just_enabled:
                show_banner = True
            if proxy_state.hello_requested:
                show_banner = True

        # derive the raw prompt from the last user message for history
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

        is_command_only = False
        if commands_processed:
            if not processed_messages:
                is_command_only = True
            else:
                last_msg = processed_messages[-1]
                if isinstance(last_msg.content, str):
                    is_command_only = not last_msg.content.strip()
                elif isinstance(last_msg.content, list):
                    is_command_only = not any(
                        part.text.strip() 
                        for part in last_msg.content 
                        if isinstance(part, models.MessageContentPartText)
                    )

        confirmation_text = ""
        if parser is not None:
            confirmation_text = "\n".join(
                r.message for r in parser.results if r.message
            )

        if is_command_only:
            pieces = []
            if proxy_state.interactive_mode and show_banner:
                pieces.append(_welcome_banner(session_id))
            elif show_banner:
                pieces.append(_welcome_banner(session_id))
            if confirmation_text:
                pieces.append(confirmation_text)
            if not pieces:
                pieces.append("Proxy command processed. No query sent to LLM.")
            response_text = wrap_proxy_message(session.agent, "\n".join(pieces))
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
                choices=[
                    models.ChatCompletionChoice(
                        index=0,
                        message=models.ChatCompletionChoiceMessage(
                            role="assistant",
                            content=response_text,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=models.CompletionUsage(
                    prompt_tokens=0, completion_tokens=0, total_tokens=0
                ),
            )

        if not processed_messages:
            raise HTTPException(
                status_code=400,
                detail="No messages provided in the request or messages became empty after processing.",
            )

        if http_request.app.state.force_set_project and proxy_state.project is None:
            raise HTTPException(
                status_code=400,
                detail="Project name not set. Use !/set(project=<name>) before sending prompts.",
            )

        effective_model = proxy_state.get_effective_model(request_data.model)

        async def _call_backend(b_type: str, model: str, key_name: str, api_key: str):
            if b_type == "gemini":
                retry_at = http_request.app.state.rate_limits.get(
                    "gemini", model, key_name
                )
                if retry_at:
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        },
                    )
                try:
                    result = await http_request.app.state.gemini_backend.chat_completions(
                        request_data=request_data,
                        processed_messages=processed_messages,
                        effective_model=model,
                        project=proxy_state.project,
                        gemini_api_base_url=cfg["gemini_api_base_url"],
                        key_name=key_name,
                        api_key=api_key,
                        prompt_redactor=(
                            http_request.app.state.api_key_redactor
                            if http_request.app.state.api_key_redaction_enabled
                            else None
                        ),
                    )
                    logger.debug(f"Result from Gemini backend chat_completions: {result}")
                    return result
                except HTTPException as e:
                    if e.status_code == 429:
                        delay = parse_retry_delay(e.detail)
                        if delay:
                            http_request.app.state.rate_limits.set(
                                "gemini", model, key_name, delay
                            )
                    raise
            retry_at = http_request.app.state.rate_limits.get(
                "openrouter", model, key_name
            )
            if retry_at:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "message": "Backend rate limited, retry later",
                        "retry_after": int(retry_at - time.time()),
                    },
                )
            try:
                result = await http_request.app.state.openrouter_backend.chat_completions(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=model,
                    openrouter_api_base_url=cfg["openrouter_api_base_url"],
                    openrouter_headers_provider=lambda n, k: get_openrouter_headers(
                        cfg, k
                    ),
                    key_name=key_name,
                    api_key=api_key,
                    project=proxy_state.project,
                    prompt_redactor=(
                        http_request.app.state.api_key_redactor
                        if http_request.app.state.api_key_redaction_enabled
                        else None
                    ),
                )
                logger.debug(f"Result from OpenRouter backend chat_completions: {result}")
                return result
            except HTTPException as e:
                if e.status_code == 429:
                    delay = parse_retry_delay(e.detail)
                    if delay:
                        http_request.app.state.rate_limits.set(
                            "openrouter", model, key_name, delay
                        )
                raise

        route = proxy_state.failover_routes.get(effective_model)
        attempts: list[tuple[str, str, str, str]] = []
        if route:
            # Defensive: ensure elements is a list if present, else empty list
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
                for kname, key in _keys_for(cfg, b):  # Pass cfg
                    attempts.append((b, m, kname, key))
            elif policy == "m":
                for el in elems:
                    b, m = el.split(":", 1)
                    keys = _keys_for(cfg, b)
                    if not keys:
                        continue
                    kname, key = keys[0]
                    attempts.append((b, m, kname, key))
            elif policy == "km":
                for el in elems:
                    b, m = el.split(":", 1)
                    for kname, key in _keys_for(cfg, b):  # Pass cfg
                        attempts.append((b, m, kname, key))
            elif policy == "mk":
                backends_used = {el.split(":", 1)[0] for el in elems}
                key_map = {b: _keys_for(cfg, b) for b in backends_used}  # Pass cfg
                max_len = max(len(v) for v in key_map.values()) if key_map else 0
                for i in range(max_len):
                    for el in elems:
                        b, m = el.split(":", 1)
                        if i < len(key_map[b]):
                            kname, key = key_map[b][i]
                            attempts.append((b, m, kname, key))
        else:
            default_keys = _keys_for(cfg, backend_type)  # Pass cfg
            if not default_keys:
                raise HTTPException(
                    status_code=500,
                    detail=f"No API keys configured for the default backend: {backend_type}",
                )
            attempts.append(
                (
                    backend_type,
                    effective_model,
                    default_keys[0][0],
                    default_keys[0][1],
                )
            )

        last_error: HTTPException | None = None
        response = None
        used_backend = backend_type
        used_model = effective_model
        success = False
        for b, m, kname, key in attempts:
            logger.debug(f"Attempting backend: {b}, model: {m}, key_name: {kname}")
            try:
                response = await _call_backend(b, m, kname, key)
                used_backend = b
                used_model = m
                success = True
                logger.debug(
                    f"Attempt successful for backend: {b}, model: {m}, key_name: {kname}"
                )
                break
            except HTTPException as e:
                logger.debug(
                    f"Attempt failed for backend: {b}, model: {m}, key_name: {kname} with HTTPException: {e.status_code} - {e.detail}"
                )
                if e.status_code == 429:
                    last_error = e
                    continue
                raise
        if not success:
            error_msg = last_error.detail if last_error else "all backends failed"
            status_code = (
                last_error.status_code if last_error else 500
            )  # Use last_error's status code, default to 500

            # Always return a valid OpenAI-compatible response structure
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
                            "content": f"All backends failed: {error_msg}",
                        },
                        "finish_reason": "error",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "error": error_msg,
            }
            raise HTTPException(
                status_code=status_code, detail=response_content
            )  # Raise HTTPException with correct status code

        logging.debug(f"Response from _call_backend: {response}")  # Added debug log

        # At this point, response is expected to be a dictionary or StreamingResponse.
        if isinstance(response, StreamingResponse):
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=used_backend,
                    model=used_model,
                    project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response="<streaming>",
                )
            )
            return response
        if response is None:
            backend_response: Dict[str, Any] = {}
        else:
            backend_response: Dict[str, Any] = response  # Changed to direct assignment

        logging.debug(f"Backend response before defensive check: {backend_response}")
        logging.debug(f"Type of backend_response: {type(backend_response)}")
        logging.debug(f"'choices' in backend_response: {'choices' in backend_response}")
        logging.debug(
            f"backend_response.get('choices'): {backend_response.get('choices')}"
        )

        # Defensive: ensure choices key exists for downstream code
        if "choices" not in backend_response:
            backend_response["choices"] = [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "(no response)"},
                    "finish_reason": "error",
                }
            ]

        if isinstance(backend_response, dict):
            logging.debug(
                f"Backend response (non-streaming): {json.dumps(backend_response, indent=2)}"
            )
        else:
            logging.debug(
                f"Backend response (non-streaming): {backend_response}"
            )  # Log as is if not a dict

        if proxy_state.interactive_mode:
            prefix_parts = []
            if show_banner:
                prefix_parts.append(_welcome_banner(session_id))
            if confirmation_text:
                prefix_parts.append(confirmation_text)
            if prefix_parts:
                prefix_text = wrap_proxy_message(session.agent, "\n".join(prefix_parts))
                orig = (
                    backend_response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                backend_response["choices"][0]["message"]["content"] = (
                    prefix_text + "\n" + orig if orig else prefix_text
                )

        usage_data = backend_response.get("usage")
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt,
                handler="backend",
                backend=used_backend,
                model=used_model,
                project=proxy_state.project,
                parameters=request_data.model_dump(exclude_unset=True),
                response=backend_response.get("choices", [{}])[0]
                .get("message", {})
                .get("content"),
                usage=(
                    models.CompletionUsage(**usage_data)
                    if isinstance(usage_data, dict)
                    else None
                ),
            )
        )
        proxy_state.hello_requested = False
        proxy_state.interactive_just_enabled = False
        logging.debug(f"Final backend_response: {backend_response}")  # Added debug log
        return backend_response

    @app.get("/models", dependencies=[Depends(verify_client_auth)])
    async def list_all_models(http_request: Request):
        data = []
        if "openrouter" in http_request.app.state.functional_backends:
            for m in http_request.app.state.openrouter_backend.get_available_models():
                data.append({"id": f"openrouter:{m}"})
        if "gemini" in http_request.app.state.functional_backends:
            for m in http_request.app.state.gemini_backend.get_available_models():
                data.append({"id": f"gemini:{m}"})
        return {"object": "list", "data": data}

    @app.get("/v1/models", dependencies=[Depends(verify_client_auth)])
    async def list_models(http_request: Request):
        """Return cached models from all functional backends in OpenAI format."""
        data = []
        if "openrouter" in http_request.app.state.functional_backends:
            for m in http_request.app.state.openrouter_backend.get_available_models():
                data.append({"id": f"openrouter:{m}"})
        if "gemini" in http_request.app.state.functional_backends:
            for m in http_request.app.state.gemini_backend.get_available_models():
                data.append({"id": f"gemini:{m}"})
        return {"object": "list", "data": data}

    return app


# Create a default application instance for importers
if __name__ != "__main__":
    app = build_app()

if __name__ == "__main__":
    from src.core.cli import main as cli_main

    cli_main(build_app_fn=build_app)
