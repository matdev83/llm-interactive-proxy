#!/usr/bin/env python3
"""
Test script to check if gemini-2.5-flash-thinking model is available via antigravity-oauth backend.

This script:
1. Initializes the Antigravity backend
2. Loads available models
3. Checks if gemini-2.5-flash-thinking is in the list
4. Attempts to validate the model
5. Reports findings
"""

import asyncio
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add src to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


async def test_thinking_model_availability():
    """Test if gemini-2.5-flash-thinking model is available on Antigravity backend."""

    logger.info("Starting gemini-2.5-flash-thinking availability test...")

    # Create minimal config
    config = AppConfig()

    # Create translation service
    translation_service = TranslationService()

    # Create client
    client = httpx.AsyncClient(timeout=60.0)

    try:
        # Initialize backend
        logger.info("Initializing AntigravityOAuthConnector...")
        backend = AntigravityOAuthConnector(
            client=client, config=config, translation_service=translation_service
        )

        await backend.initialize()
        logger.info("Backend initialized successfully")

        # Ensure models are loaded
        logger.info("Loading available models...")
        await backend._ensure_models_loaded()

        # Get available models
        available_models = backend._get_available_models_set()
        logger.info(f"Total available models: {len(available_models)}")

        # List all available gemini-2.5 models
        gemini_2_5_models = sorted([m for m in available_models if "gemini-2.5" in m])
        logger.info(f"Available gemini-2.5 models ({len(gemini_2_5_models)}):")
        for model in gemini_2_5_models:
            logger.info(f"  - {model}")

        # Check for thinking model specifically
        thinking_model = "gemini-2.5-flash-thinking"
        is_available = thinking_model in available_models

        logger.info(f"\n{'='*60}")
        logger.info(
            f"Model '{thinking_model}' availability: {'YES' if is_available else 'NO'}"
        )
        logger.info(f"{'='*60}")

        # Try to validate the model
        if is_available:
            try:
                backend.validate_model(thinking_model)
                logger.info(f"Validation passed: Model '{thinking_model}' can be used")
                return True
            except BackendError as e:
                logger.error(f"Validation failed: {e.message}")
                return False
        else:
            logger.warning(f"Model '{thinking_model}' not in available models list")
            logger.info("Attempting validation anyway (may fail)...")
            try:
                backend.validate_model(thinking_model)
                logger.info("Validation passed (using hardcoded fallback list)")
                return True
            except BackendError as e:
                logger.error(f"Validation failed: {e.message}")
                return False

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        return False

    finally:
        await client.aclose()


async def main():
    """Run the test."""
    success = await test_thinking_model_availability()

    if success:
        logger.info(
            "\nResult: gemini-2.5-flash-thinking CAN be used with antigravity-oauth"
        )
        return 0
    else:
        logger.error(
            "\nResult: gemini-2.5-flash-thinking CANNOT be used with antigravity-oauth"
        )
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
