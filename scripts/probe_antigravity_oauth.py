#!/usr/bin/env python
"""
Temporary probe for the antigravity-oauth backend.

This script initializes the Antigravity OAuth connector, sends a simple
prompt, and prints the response. It is intended for manual diagnostics; it will
gracefully report missing credentials instead of crashing.

Examples:
    ./.venv/Scripts/python.exe scripts/probe_antigravity_oauth.py
    ./.venv/Scripts/python.exe scripts/probe_antigravity_oauth.py \\
        --prompt "Say hello" --model gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from src.connectors.antigravity_oauth import (
    ANTIGRAVITY_SANDBOX_ENDPOINT,
    AntigravityOAuthConnector,
)
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.translation_service import TranslationService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("probe_antigravity_oauth")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the antigravity-oauth backend with a simple prompt."
    )
    parser.add_argument(
        "--prompt",
        default="Hello from the Antigravity probe!",
        help="Prompt to send to the backend.",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Model name to use for the request.",
    )
    parser.add_argument(
        "--base-url",
        default=ANTIGRAVITY_SANDBOX_ENDPOINT,
        help="Base URL for the Code Assist API (defaults to Antigravity sandbox).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream the response instead of waiting for completion.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available models reported by the Antigravity endpoint and exit.",
    )
    return parser.parse_args()


async def run_probe(args: argparse.Namespace) -> int:
    config = AppConfig()
    services = ServiceCollection()
    services.add_singleton(TranslationService)
    services.add_singleton(ITranslationService, TranslationService)  # type: ignore[type-abstract]
    provider = services.build_service_provider()
    translation_service = provider.get_required_service(ITranslationService)

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        connector = AntigravityOAuthConnector(
            client=client,
            config=config,
            translation_service=translation_service,
            name="antigravity-oauth",
        )

        await connector.initialize(gemini_api_base_url=args.base_url)
        if not connector.is_backend_functional():
            errors = connector.get_validation_errors()
            logger.error(
                "Backend is not functional. Credential or initialization issues: %s",
                "; ".join(errors) if errors else "unknown error",
            )
            logger.error(
                "Ensure Antigravity is installed and signed in, or set ANTIGRAVITY_STATE_DB."
            )
            return 2

        if args.list_models:
            await connector._ensure_models_loaded()
            models = connector.available_models
            if not models:
                logger.error("No models discovered.")
                return 3
            logger.info("Available models (%d):", len(models))
            for m in models:
                logger.info("- %s", m)
            return 0

        request = CanonicalChatRequest(
            model=args.model,
            messages=[ChatMessage(role="user", content=args.prompt)],
            stream=args.stream,
        )

        try:
            response = await connector.chat_completions(
                request_data=request,
                processed_messages=[],
                effective_model=args.model,
            )
        except Exception as exc:  # pragma: no cover - probe diagnostics
            logger.error("Request failed: %s", exc, exc_info=True)
            return 1

        if args.stream and hasattr(response, "content") and response.content:
            logger.info("Streaming response:")
            async for chunk in response.content:  # type: ignore[attr-defined]
                logger.info("chunk: %s", chunk.content)
        else:
            payload: Any = getattr(response, "content", None)
            logger.info("Response content:\n%s", payload)

    return 0


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run_probe(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
