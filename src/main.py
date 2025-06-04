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
from src.proxy_logic import process_commands_in_messages, ProxyState
from src.connectors import OpenRouterBackend, GeminiBackend


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _load_config() -> Dict[str, Any]:
    load_dotenv()
    return {
        "backend": os.getenv("LLM_BACKEND", "openrouter"),
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
        "openrouter_api_base_url": os.getenv("OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"),
        "gemini_api_key": os.getenv("GEMINI_API_KEY"),
        "gemini_api_base_url": os.getenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com"),
        "app_site_url": os.getenv("APP_SITE_URL", "http://localhost:8000"),
        "app_x_title": os.getenv("APP_X_TITLE", "InterceptorProxy"),
        "proxy_port": int(os.getenv("PROXY_PORT", "8000")),
        "proxy_host": os.getenv("PROXY_HOST", "0.0.0.0"),
        "proxy_timeout": int(os.getenv("PROXY_TIMEOUT", os.getenv("OPENROUTER_TIMEOUT", "300"))),
    }


def get_openrouter_headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg['openrouter_api_key']}" if cfg["openrouter_api_key"] else "",
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
        app.state.proxy_state = ProxyState()
        app.state.backend_type = cfg["backend"]
        if cfg["backend"] == "gemini":
            backend = GeminiBackend(client)
            app.state.gemini_backend = backend
        else:
            backend = OpenRouterBackend(client)
            app.state.openrouter_backend = backend
        app.state.backend = backend
        yield
        await client.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def root():
        return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

    @app.post("/v1/chat/completions", response_model=Union[models.CommandProcessedChatCompletionResponse, Dict[str, Any]])
    async def chat_completions(request_data: models.ChatCompletionRequest, http_request: Request):
        backend = http_request.app.state.backend
        proxy_state: ProxyState = http_request.app.state.proxy_state

        processed_messages, commands_processed = process_commands_in_messages(request_data.messages, proxy_state)

        is_command_only = False
        if commands_processed and not any(
            (msg.content if isinstance(msg.content, str) else "").strip() for msg in processed_messages
        ):
            is_command_only = True

        if is_command_only:
            return models.CommandProcessedChatCompletionResponse(
                id="proxy_cmd_processed",
                object="chat.completion",
                created=int(datetime.utcnow().timestamp()),
                model=proxy_state.get_effective_model(request_data.model),
                choices=[
                    models.ChatCompletionChoice(
                        index=0,
                        message=models.ChatCompletionChoiceMessage(role="assistant", content="Proxy command processed. No query sent to LLM."),
                        finish_reason="stop",
                    )
                ],
                usage=models.CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )

        if not processed_messages:
            raise HTTPException(status_code=400, detail="No messages provided in the request or messages became empty after processing.")

        effective_model = proxy_state.get_effective_model(request_data.model)

        if http_request.app.state.backend_type == "gemini":
            response = await backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                gemini_api_base_url=cfg["gemini_api_base_url"],
                gemini_api_key=cfg["gemini_api_key"],
            )
            return response

        response = await backend.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            openrouter_api_base_url=cfg["openrouter_api_base_url"],
            openrouter_headers_provider=lambda: get_openrouter_headers(cfg),
        )
        if isinstance(response, StreamingResponse):
            return response
        return response

    @app.get("/v1/models")
    async def list_models(http_request: Request):
        backend = http_request.app.state.backend
        if http_request.app.state.backend_type == "gemini":
            return await backend.list_models(
                gemini_api_base_url=cfg["gemini_api_base_url"],
                gemini_api_key=cfg["gemini_api_key"],
            )
        return await backend.list_models(
            openrouter_api_base_url=cfg["openrouter_api_base_url"],
            openrouter_headers_provider=lambda: get_openrouter_headers(cfg),
        )

    return app


# Create a default application instance for importers
app = build_app()


# ---------------------------------------------------------------------------
# CLI utilities
# ---------------------------------------------------------------------------

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")
    parser.add_argument("--backend", choices=["openrouter", "gemini"], default=os.getenv("LLM_BACKEND", "openrouter"))
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-api-base-url")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--gemini-api-base-url")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--timeout", type=int)
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
    }
    for attr, env_name in mappings.items():
        value = getattr(args, attr)
        if value is not None:
            os.environ[env_name] = str(value)
    return _load_config()


def main(argv: list[str] | None = None) -> None:
    args = parse_cli_args(argv)
    cfg = apply_cli_args(args)
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    app = build_app(cfg)
    import uvicorn

    uvicorn.run(app, host=cfg["proxy_host"], port=cfg["proxy_port"])


if __name__ == "__main__":
    main()
