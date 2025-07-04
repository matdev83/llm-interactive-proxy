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

import httpx # Moved up
from fastapi import FastAPI, HTTPException, Request, Depends # Moved up
from fastapi.responses import StreamingResponse # Moved up

from src import models # Moved up
from src.proxy_logic import ProxyState # Moved up
from src.command_parser import CommandParser # Moved up
from src.session import SessionManager, SessionInteraction # Moved up
from src.agents import detect_agent, wrap_proxy_message # Moved up
from src.connectors import OpenRouterBackend, GeminiBackend # Moved up
from src.security import APIKeyRedactor # Moved up
from src.rate_limit import RateLimitRegistry, parse_retry_delay # Moved up
from src.core.metadata import _load_project_metadata # Moved up
from src.core.config import _load_config, get_openrouter_headers, _keys_for # Moved up
from src.core.persistence import ConfigManager # Moved up

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def build_app(cfg: Dict[str, Any] | None = None, *, config_file: str | None = None) -> FastAPI:
    cfg = cfg or _load_config()

    disable_auth = cfg.get("disable_auth", False)
    api_key = os.getenv("LLM_INTERACTIVE_PROXY_API_KEY")
    # generated_key = False # F841: Unused local variable
    if not disable_auth:
        if not api_key:
            api_key = secrets.token_urlsafe(32)
            # generated_key = True # F841: Unused local variable
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
            models_count = len(app.state.openrouter_backend.get_available_models())
            backend_info.append(f"openrouter (K:{keys}, M:{models_count})")
        if "gemini" in functional:
            keys = len(cfg.get("gemini_api_keys", {}))
            models_count = len(app.state.gemini_backend.get_available_models())
            backend_info.append(f"gemini (K:{keys}, M:{models_count})")
        backends_str = ", ".join(sorted(backend_info))
        return (
            f"Hello, this is {project_name} {project_version}\n"
            f"Session id: {session_id}\n"
            f"Functional backends: {backends_str}\n"
            f"Type {cfg['command_prefix']}help for list of available commands"
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
                key_name, current_api_key = openrouter_api_keys_list[0]
                await openrouter_backend.initialize(
                    openrouter_api_base_url=cfg["openrouter_api_base_url"],
                    openrouter_headers_provider=lambda n, k: get_openrouter_headers(
                        cfg, k
                    ),
                    key_name=key_name,
                    api_key=current_api_key,
                )
                # Check if models were successfully fetched during initialization
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
        app.state.functional_backends = functional

        backend_type_str = cfg.get("backend")
        if backend_type_str:
            if functional and backend_type_str not in functional:
                raise ValueError(f"default backend {backend_type_str} is not functional")
        else:
            if len(functional) == 1:
                backend_type_str = next(iter(functional))
            elif len(functional) > 1:
                raise ValueError(
                    "Multiple functional backends, specify --default-backend"
                )
            else:
                backend_type_str = "openrouter" # Default if no functional backends (e.g. for testing)
        app.state.backend_type = backend_type_str
        app.state.initial_backend_type = backend_type_str

        app.state.backend = gemini_backend if backend_type_str == "gemini" else openrouter_backend


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
        # backend_type = http_request.app.state.backend_type # F841: Unused (re-assigned below)
        # backend = http_request.app.state.backend # F841: Unused (re-assigned below)
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

        current_backend_type = "" # Initialize to avoid potential UnboundLocalError if not set by logic below
        current_backend_obj = None

        if proxy_state.override_backend:
            current_backend_type = proxy_state.override_backend
            if proxy_state.invalid_override:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "invalid or unsupported model",
                        "model": f"{proxy_state.override_backend}:{proxy_state.override_model}",
                    },
                )
            if current_backend_type == "openrouter":
                current_backend_obj = http_request.app.state.openrouter_backend
            elif current_backend_type == "gemini":
                current_backend_obj = http_request.app.state.gemini_backend
            else: # Should not happen if override_backend is validated by set command
                raise HTTPException(
                    status_code=400, detail=f"unknown backend {current_backend_type}"
                )
        else:
            current_backend_type = http_request.app.state.backend_type
            current_backend_obj = http_request.app.state.backend


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
        else:
            processed_messages = request_data.messages
            commands_processed = False

        # Re-evaluate backend after commands, as they might change it
        if proxy_state.override_backend:
            current_backend_type = proxy_state.override_backend
            if current_backend_type == "openrouter":
                current_backend_obj = http_request.app.state.openrouter_backend
            elif current_backend_type == "gemini":
                current_backend_obj = http_request.app.state.gemini_backend
            # No else needed here, as invalid_override check happened before command processing
        else:
            current_backend_type = http_request.app.state.backend_type
            current_backend_obj = http_request.app.state.backend # This is the global default

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
        if commands_processed and not any(
            (msg.content if isinstance(msg.content, str) else "").strip()
            for msg in processed_messages
        ):
            is_command_only = True

        confirmation_text = ""
        if parser is not None:
            confirmation_text = "\n".join(
                r.message for r in parser.results if r.message
            )

        if is_command_only:
            pieces = []
            if proxy_state.interactive_mode and show_banner:
                pieces.append(_welcome_banner(session_id))
            elif show_banner: # show_banner implies interactive_mode or hello_requested
                pieces.append(_welcome_banner(session_id))
            if confirmation_text:
                pieces.append(confirmation_text)
            if not pieces: # Default if no banner and no confirmation
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

        async def _call_backend(b_type: str, model_to_call: str, key_name_to_use: str, api_key_to_use: str):
            target_backend_obj = None
            if b_type == "gemini":
                target_backend_obj = http_request.app.state.gemini_backend
            elif b_type == "openrouter":
                target_backend_obj = http_request.app.state.openrouter_backend
            else: # Should not be reached if inputs are validated
                raise ValueError(f"Invalid backend type in _call_backend: {b_type}")


            retry_at = http_request.app.state.rate_limits.get(
                b_type, model_to_call, key_name_to_use
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
                # Common arguments for both backends
                common_args = {
                    "request_data": request_data,
                    "processed_messages": processed_messages,
                    "effective_model": model_to_call, # Pass the specific model for this attempt
                    "project": proxy_state.project,
                    "key_name": key_name_to_use,
                    "api_key": api_key_to_use,
                    "prompt_redactor": (
                        http_request.app.state.api_key_redactor
                        if http_request.app.state.api_key_redaction_enabled
                        else None
                    ),
                }
                if b_type == "gemini":
                    return await target_backend_obj.chat_completions(
                        **common_args,
                        gemini_api_base_url=cfg["gemini_api_base_url"],
                    )
                # else openrouter
                return await target_backend_obj.chat_completions(
                    **common_args,
                    openrouter_api_base_url=cfg["openrouter_api_base_url"],
                    openrouter_headers_provider=lambda n, k: get_openrouter_headers(
                        cfg, k
                    ),
                )
            except HTTPException as e:
                if e.status_code == 429:
                    delay = parse_retry_delay(e.detail)
                    if delay:
                        http_request.app.state.rate_limits.set(
                            b_type, model_to_call, key_name_to_use, delay
                        )
                raise


        route = proxy_state.failover_routes.get(effective_model)
        attempts: list[tuple[str, str, str, str]] = []
        if route:
            elements = route.get("elements", [])
            if isinstance(elements, dict): # Compatibility with older config
                elems_list = list(elements.values())
            elif isinstance(elements, list):
                elems_list = elements
            else:
                elems_list = []

            policy = route.get("policy", "k") # Default to 'k' (known good)

            if policy == "k" and elems_list:
                b, m = elems_list[0].split(":", 1)
                for kname, key_val in _keys_for(cfg, b):
                    attempts.append((b, m, kname, key_val))
            elif policy == "m":
                for el_str in elems_list:
                    b, m = el_str.split(":", 1)
                    keys_for_b = _keys_for(cfg, b)
                    if not keys_for_b:
                        continue
                    kname, key_val = keys_for_b[0] # Use first key for this backend
                    attempts.append((b, m, kname, key_val))
            elif policy == "km":
                for el_str in elems_list:
                    b, m = el_str.split(":", 1)
                    for kname, key_val in _keys_for(cfg, b):
                        attempts.append((b, m, kname, key_val))
            elif policy == "mk":
                backends_used_in_route = {el.split(":", 1)[0] for el in elems_list}
                key_map_for_route = {b_str: _keys_for(cfg, b_str) for b_str in backends_used_in_route}
                max_keys_len = max(len(v) for v in key_map_for_route.values()) if key_map_for_route else 0
                for i in range(max_keys_len):
                    for el_str in elems_list:
                        b, m = el_str.split(":", 1)
                        if i < len(key_map_for_route[b]):
                            kname, key_val = key_map_for_route[b][i]
                            attempts.append((b, m, kname, key_val))
        else: # No specific route for effective_model, use default behavior
            default_keys = _keys_for(cfg, current_backend_type)
            if not default_keys:
                raise HTTPException(
                    status_code=500,
                    detail=f"No API keys configured for the backend: {current_backend_type}",
                )
            # Attempt with all keys for the current_backend_type and effective_model
            for kname, key_val in default_keys:
                 attempts.append((current_backend_type, effective_model, kname, key_val))


        last_error: HTTPException | None = None
        response_from_backend = None
        used_backend_type = current_backend_type
        used_model_name = effective_model
        success = False

        for b_attempt, m_attempt, kname_attempt, key_attempt in attempts:
            logger.debug(f"Attempting backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt}")
            try:
                response_from_backend = await _call_backend(b_attempt, m_attempt, kname_attempt, key_attempt)
                used_backend_type = b_attempt
                used_model_name = m_attempt
                success = True
                logger.debug(
                    f"Attempt successful for backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt}"
                )
                break
            except HTTPException as e:
                logger.debug(
                    f"Attempt failed for backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt} with HTTPException: {e.status_code} - {e.detail}"
                )
                last_error = e # Store last error
                if e.status_code == 429: # If rate limited, continue to next attempt
                    continue
                # For other errors (400, 401, 500 from backend), re-raise immediately as they are likely not recoverable by trying other keys/models in the route
                raise

        if not success:
            # If all attempts failed, raise the last encountered error or a generic one
            error_to_raise = last_error if last_error else HTTPException(status_code=503, detail="All backend attempts failed.")

            # Ensure the error detail is a dict for OpenAI compatibility if it's not already
            detail_content = error_to_raise.detail
            if not isinstance(detail_content, dict):
                detail_content = {"message": str(detail_content), "type": "proxy_error"}

            # Construct a valid OpenAI-like error response if not already one
            if not ("choices" in detail_content and "model" in detail_content):
                 final_error_detail = {
                    "id": "error_proxy_exhausted",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": effective_model, # The model initially requested or resolved before routing
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": detail_content.get("message", "All backend attempts failed."),
                            },
                            "finish_reason": "error",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "error": detail_content # Include original or constructed error detail
                }
            else:
                final_error_detail = detail_content # It's already an OpenAI-like error structure

            raise HTTPException(status_code=error_to_raise.status_code, detail=final_error_detail)


        logging.debug(f"Response from _call_backend: {response_from_backend}")

        if isinstance(response_from_backend, StreamingResponse):
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=used_backend_type,
                    model=used_model_name,
                    project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response="<streaming>",
                )
            )
            # Apply banner to streaming response if needed
            if proxy_state.interactive_mode and (show_banner or confirmation_text):
                # This requires a more complex handling for prepending to streams
                # For now, we might skip banner for streams or find a way to inject it.
                # Simplest: log that banner was skipped for stream.
                logger.info("Interactive banner/confirmation skipped for streaming response.")
            return response_from_backend

        # Non-streaming response (should be a dict)
        backend_response_dict: Dict[str, Any] = response_from_backend if isinstance(response_from_backend, dict) else {}

        logging.debug(f"Backend response before defensive check: {backend_response_dict}")
        logging.debug(f"Type of backend_response_dict: {type(backend_response_dict)}")

        if "choices" not in backend_response_dict or not backend_response_dict["choices"]:
            backend_response_dict["choices"] = [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "(no valid response choices from backend)"},
                    "finish_reason": "error",
                }
            ]
        if "message" not in backend_response_dict["choices"][0]:
             backend_response_dict["choices"][0]["message"] = {"role": "assistant", "content": "(backend choice missing message)"}
        if "content" not in backend_response_dict["choices"][0]["message"]:
             backend_response_dict["choices"][0]["message"]["content"] = "(backend choice missing content)"


        if proxy_state.interactive_mode:
            prefix_parts = []
            if show_banner:
                prefix_parts.append(_welcome_banner(session_id))
            if confirmation_text:
                prefix_parts.append(confirmation_text)
            if prefix_parts:
                prefix_text = wrap_proxy_message(session.agent, "\n".join(prefix_parts))
                orig_content = backend_response_dict["choices"][0]["message"].get("content", "")
                backend_response_dict["choices"][0]["message"]["content"] = (
                    f"{prefix_text}\n{orig_content}" if orig_content else prefix_text
                )

        usage_data = backend_response_dict.get("usage")
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt,
                handler="backend",
                backend=used_backend_type,
                model=used_model_name,
                project=proxy_state.project,
                parameters=request_data.model_dump(exclude_unset=True),
                response=backend_response_dict["choices"][0]["message"].get("content"),
                usage=(
                    models.CompletionUsage(**usage_data)
                    if isinstance(usage_data, dict)
                    else None
                ),
            )
        )
        proxy_state.hello_requested = False
        proxy_state.interactive_just_enabled = False
        logging.debug(f"Final backend_response_dict: {backend_response_dict}")
        return backend_response_dict

    @app.get("/models", dependencies=[Depends(verify_client_auth)])
    async def list_all_models(http_request: Request):
        data = []
        if "openrouter" in http_request.app.state.functional_backends:
            for m in http_request.app.state.openrouter_backend.get_available_models():
                data.append({"id": f"openrouter:{m}"}) # Use model "id" from openrouter
        if "gemini" in http_request.app.state.functional_backends:
            for m in http_request.app.state.gemini_backend.get_available_models():
                data.append({"id": f"gemini:{m}"}) # Use model "id" from gemini
        return {"object": "list", "data": data}

    @app.get("/v1/models", dependencies=[Depends(verify_client_auth)])
    async def list_models_v1(http_request: Request): # Renamed to avoid conflict if routes merge
        """Return cached models from all functional backends in OpenAI format."""
        data = []
        # Ensure functional_backends is populated
        functional_b = http_request.app.state.functional_backends if hasattr(http_request.app.state, 'functional_backends') else []

        if "openrouter" in functional_b:
            openrouter_models = http_request.app.state.openrouter_backend.get_available_models()
            for m_id in openrouter_models: # Assuming get_available_models returns list of strings (model IDs)
                data.append({"id": f"openrouter:{m_id}", "object": "model", "owned_by": "openrouter"})

        if "gemini" in functional_b:
            gemini_models = http_request.app.state.gemini_backend.get_available_models()
            for m_id in gemini_models: # Assuming get_available_models returns list of strings (model IDs)
                data.append({"id": f"gemini:{m_id}", "object": "model", "owned_by": "google"})

        return {"object": "list", "data": data}

    return app


if __name__ == "__main__":
    from src.core.cli import main as cli_main

    cli_main(build_app_fn=build_app)
