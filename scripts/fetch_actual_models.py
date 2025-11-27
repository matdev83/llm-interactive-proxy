#!/usr/bin/env python3
"""
Fetch and display the actual available models from the Antigravity backend.
"""

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG, format="%(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import httpx
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.translation_service import TranslationService


async def fetch_models():
    """Fetch actual models from the backend."""

    config = AppConfig()
    services = ServiceCollection()
    services.add_singleton(TranslationService)
    services.add_singleton(ITranslationService, TranslationService)  # type: ignore[type-abstract]
    provider = services.build_service_provider()
    translation_service = provider.get_required_service(ITranslationService)
    client = httpx.AsyncClient(timeout=60.0)

    try:
        backend = GeminiOAuthAntigravityConnector(
            client=client, config=config, translation_service=translation_service
        )

        await backend.initialize()

        # Try to load models from API
        print("\n" + "=" * 70)
        print("FETCHING AVAILABLE MODELS FROM ANTIGRAVITY BACKEND")
        print("=" * 70)

        await backend._ensure_models_loaded()

        models = backend._get_available_models_set()

        print(f"\nTotal models found: {len(models)}\n")
        print("Available models:")
        for model in sorted(models):
            print(f"  - {model}")

        # Check for thinking model
        print("\n" + "-" * 70)
        thinking_models = [m for m in sorted(models) if "thinking" in m.lower()]
        print(f"\nThinking models available: {len(thinking_models)}")
        if thinking_models:
            for model in thinking_models:
                print(f"  - {model}")
        else:
            print("  (none)")

        # Check for 2.5 flash thinking specifically
        target = "gemini-2.5-flash-thinking"
        print(f"\nSearching for '{target}':")
        if target in models:
            print("  FOUND!")
        else:
            print("  NOT FOUND")

        print("\n" + "=" * 70 + "\n")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

    finally:
        await client.aclose()


async def main():
    """Run the test."""
    await fetch_models()


if __name__ == "__main__":
    asyncio.run(main())
