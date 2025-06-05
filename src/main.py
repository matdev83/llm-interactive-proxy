from __future__ import annotations

import argparse
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Union

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from src import models
from src.proxy_logic import ProxyState
from src.command_parser import CommandParser
from src.session import SessionManager, SessionInteraction
from src.connectors import OpenRouterBackend, GeminiBackend
from src.security import APIKeyRedactor


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _collect_api_keys(base_name: str) -> Dict[str, str]:
    """Collect API keys as a mapping of env var names to values."""

    single = os.getenv(base_name)
    numbered = {
        f"{base_name}_{i}": os.getenv(f"{base_name}_{i}")
        for i in range(1, 21)
        if os.getenv(f"{base_name}_{i}")
    }

    if single and numbered:
        raise ValueError(
            f"Specify either {base_name} or {base_name}_<n> (1-20), not both"
        )

    if single:
        return {base_name: single}

    return numbered


def _load_config() -> Dict[str, Any]:
    load_dotenv()

    openrouter_keys = _collect_api_keys("OPENROUTER_API_KEY")
    gemini_keys = _collect_api_keys("GEMINI_API_KEY")

    def _str_to_bool(val: str | None, default: bool = False) -> bool:
        if val is None:
            return default
        val = val.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return default

    return {
        "backend": os.getenv("LLM_BACKEND", "openrouter"),
        "openrouter_api_key": next(iter(openrouter_keys.values())) if openrouter_keys else None,
        "openrouter_api_keys": openrouter_keys,
        "openrouter_api_base_url": os.getenv(
            "OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        "gemini_api_key": next(iter(gemini_keys.values())) if gemini_keys else None,
        "gemini_api_keys": gemini_keys,
        "gemini_api_base_url": os.getenv(
            "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com"
        ),
        "app_site_url": os.getenv("APP_SITE_URL", "http://localhost:8000"),
        "app_x_title": os.getenv("APP_X_TITLE", "InterceptorProxy"),
        "proxy_port": int(os.getenv("PROXY_PORT", "8000")),
        "proxy_host": os.getenv("PROXY_HOST", "0.0.0.0"),
        "proxy_timeout": int(
            os.getenv("PROXY_TIMEOUT", os.getenv("OPENROUTER_TIMEOUT", "300"))
        ),
        "command_prefix": os.getenv("COMMAND_PREFIX", "!/"),
        "interactive_mode": _str_to_bool(os.getenv("INTERACTIVE_MODE"), False),
    }


def get_openrouter_headers(cfg: Dict[str, Any], api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": cfg["app_site_url"],
        "X-Title": cfg["app_x_title"],
    }


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def build_app(cfg: Dict[str, Any] | None = None) -> FastAPI:
    cfg = cfg or _load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = httpx.AsyncClient(timeout=cfg["proxy_timeout"])
        app.state.httpx_client = client
        app.state.session_manager = SessionManager(
            default_interactive_mode=cfg["interactive_mode"]
        )
        app.state.command_prefix = cfg["command_prefix"]
        app.state.backend_type = cfg["backend"]
        if cfg["backend"] == "gemini":
            backend = GeminiBackend(client)
            app.state.gemini_backend = backend
        else:
            backend = OpenRouterBackend(client)
            app.state.openrouter_backend = backend
        app.state.backend = backend
        all_keys = list(cfg.get("openrouter_api_keys", {}).values()) + list(cfg.get("gemini_api_keys", {}).values())
        app.state.api_key_redactor = APIKeyRedactor(all_keys)
        yield
        await client.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def root():
        return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

    @app.post(
        "/v1/chat/completions",
        response_model=Union[
            models.CommandProcessedChatCompletionResponse, Dict[str, Any]
        ],
    )
    async def chat_completions(
        request_data: models.ChatCompletionRequest, http_request: Request
    ):
        backend = http_request.app.state.backend
        session_id = http_request.headers.get("x-session-id", "default")
        session = http_request.app.state.session_manager.get_session(session_id)
        proxy_state: ProxyState = session.proxy_state

        parser = CommandParser(proxy_state, command_prefix=http_request.app.state.command_prefix)
        processed_messages, commands_processed = parser.process_messages(
            request_data.messages
        )

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

        if is_command_only:
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="proxy",
                    model=proxy_state.get_effective_model(request_data.model),
                    project=proxy_state.project,
                    response="Proxy command processed. No query sent to LLM.",
                )
            )
            return models.CommandProcessedChatCompletionResponse(
                id="proxy_cmd_processed",
                object="chat.completion",
                created=int(datetime.utcnow().timestamp()),
                model=proxy_state.get_effective_model(request_data.model),
                choices=[
                    models.ChatCompletionChoice(
                        index=0,
                        message=models.ChatCompletionChoiceMessage(
                            role="assistant",
                            content="Proxy command processed. No query sent to LLM.",
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

        effective_model = proxy_state.get_effective_model(request_data.model)

        if http_request.app.state.backend_type == "gemini":
            key_name, api_key = (
                next(iter(cfg["gemini_api_keys"].items()))
                if cfg["gemini_api_keys"]
                else ("GEMINI_API_KEY", cfg["gemini_api_key"])
            )
            response = await backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                project=proxy_state.project,
                gemini_api_base_url=cfg["gemini_api_base_url"],
                key_name=key_name,
                api_key=api_key,
                prompt_redactor=http_request.app.state.api_key_redactor,
            )
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend="gemini",
                    model=effective_model,
                    project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response=response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content"),
                    usage=(
                        models.CompletionUsage(**response.get("usage"))
                        if response.get("usage")
                        else None
                    ),
                )
            )
            return response

        key_name, api_key = (
            next(iter(cfg["openrouter_api_keys"].items()))
            if cfg["openrouter_api_keys"]
            else ("OPENROUTER_API_KEY", cfg["openrouter_api_key"])
        )
        response = await backend.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            openrouter_api_base_url=cfg["openrouter_api_base_url"],
            openrouter_headers_provider=lambda n, k: get_openrouter_headers(cfg, k),
            key_name=key_name,
            api_key=api_key,
            project=proxy_state.project,
            prompt_redactor=http_request.app.state.api_key_redactor,
        )
        if isinstance(response, StreamingResponse):
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend="openrouter",
                    model=effective_model,
                    project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response="<streaming>",
                )
            )
            return response
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt,
                handler="backend",
                backend="openrouter",
                model=effective_model,
                project=proxy_state.project,
                parameters=request_data.model_dump(exclude_unset=True),
                response=response.get("choices", [{}])[0]
                .get("message", {})
                .get("content"),
                usage=(
                    models.CompletionUsage(**response.get("usage"))
                    if response.get("usage")
                    else None
                ),
            )
        )
        return response

    @app.get("/v1/models")
    async def list_models(http_request: Request):
        backend = http_request.app.state.backend
        if http_request.app.state.backend_type == "gemini":
            key_name, api_key = (
                next(iter(cfg["gemini_api_keys"].items()))
                if cfg["gemini_api_keys"]
                else ("GEMINI_API_KEY", cfg["gemini_api_key"])
            )
            return await backend.list_models(
                gemini_api_base_url=cfg["gemini_api_base_url"],
                key_name=key_name,
                api_key=api_key,
            )
        key_name, api_key = (
            next(iter(cfg["openrouter_api_keys"].items()))
            if cfg["openrouter_api_keys"]
            else ("OPENROUTER_API_KEY", cfg["openrouter_api_key"])
        )
        return await backend.list_models(
            openrouter_api_base_url=cfg["openrouter_api_base_url"],
            openrouter_headers_provider=lambda n, k: get_openrouter_headers(cfg, k),
            key_name=key_name,
            api_key=api_key,
        )

    return app


# Create a default application instance for importers
app = build_app()


# ---------------------------------------------------------------------------
# CLI utilities
# ---------------------------------------------------------------------------


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")
    parser.add_argument(
        "--backend",
        choices=["openrouter", "gemini"],
        default=os.getenv("LLM_BACKEND", "openrouter"),
    )
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-api-base-url")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--gemini-api-base-url")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--command-prefix")
    parser.add_argument(
        "--interactive-mode",
        action="store_true",
        default=None,
        help="Enable interactive mode by default for new sessions",
    )
    return parser.parse_args(argv)


def apply_cli_args(args: argparse.Namespace) -> Dict[str, Any]:
    mappings = {
        "backend": "LLM_BACKEND",
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "openrouter_api_base_url": "OPENROUTER_API_BASE_URL",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_api_base_url": "GEMINI_API_BASE_URL",
        "host": "PROXY_HOST",
        "port": "PROXY_PORT",
        "timeout": "PROXY_TIMEOUT",
        "command_prefix": "COMMAND_PREFIX",
        "interactive_mode": "INTERACTIVE_MODE",
    }
    for attr, env_name in mappings.items():
        value = getattr(args, attr)
        if value is not None:
            os.environ[env_name] = str(value)
    return _load_config()


def main(argv: list[str] | None = None) -> None:
    args = parse_cli_args(argv)
    cfg = apply_cli_args(args)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    app = build_app(cfg)
    import uvicorn

    uvicorn.run(app, host=cfg["proxy_host"], port=cfg["proxy_port"])


if __name__ == "__main__":
    main()
