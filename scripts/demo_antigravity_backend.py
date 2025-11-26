#!/usr/bin/env python
"""
Demo script to illustrate the working state of the gemini-oauth-antigravity backend.

This script demonstrates:
1. Listing available models from the fetchAvailableModels endpoint
2. Sending a simple chat completion request using gemini-2.5-flash-lite

Prerequisites:
- Antigravity app must be installed and authenticated
- The Antigravity state database must contain valid OAuth credentials
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from src.connectors.gemini_oauth_antigravity import (
    ANTIGRAVITY_SANDBOX_ENDPOINT,
    ANTIGRAVITY_USER_AGENT,
    GeminiOAuthAntigravityConnector,
)
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.translation_service import TranslationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def demo_list_models(connector: GeminiOAuthAntigravityConnector) -> list[str]:
    """List available models from the Antigravity backend."""
    print("\n" + "=" * 60)
    print("STEP 1: Listing Available Models")
    print("=" * 60)

    # First try the API endpoint
    try:
        result = await connector.list_models(
            gemini_api_base_url=ANTIGRAVITY_SANDBOX_ENDPOINT,
            key_name="antigravity",
            api_key="",  # Not used for OAuth
        )

        models = result.get("models", [])
        if models:
            print(f"\nFound {len(models)} models from API:\n")

            model_names = []
            for model in models:
                name = model.get("name", "").replace("models/", "")
                display_name = model.get("displayName", name)
                input_limit = model.get("inputTokenLimit", "N/A")
                output_limit = model.get("outputTokenLimit", "N/A")

                model_names.append(name)
                print(f"  - {name}")
                print(f"    Display: {display_name}")
                print(f"    Input tokens: {input_limit}, Output tokens: {output_limit}")
                print()

            return model_names

    except Exception as e:
        logger.warning(f"API model listing failed: {e}")

    # Fall back to cached/hardcoded models
    print("\n[INFO] Using cached/hardcoded model list (API endpoint not available)")

    # Ensure models are loaded
    await connector._ensure_models_loaded()

    if connector.available_models:
        print(f"\nFound {len(connector.available_models)} cached models:\n")
        for model in connector.available_models:
            print(f"  - {model}")
        print()
        return connector.available_models

    print("\n[WARNING] No models available")
    return []


async def demo_chat_completion(
    connector: GeminiOAuthAntigravityConnector, model: str = "gemini-2.5-flash-lite"
) -> None:
    """Send a simple chat completion request."""
    print("\n" + "=" * 60)
    print(f"STEP 2: Chat Completion with {model}")
    print("=" * 60)

    from src.core.domain.chat import ChatMessage, ChatRequest

    # Create proper domain message objects
    messages = [
        ChatMessage(role="user", content="Hello! Please respond with a brief greeting.")
    ]

    # Create a proper ChatRequest
    request = ChatRequest(
        model=model,
        messages=messages,
        max_tokens=100,
        temperature=0.7,
        stream=False,
    )

    print("\nRequest:")
    print(f"  Model: {model}")
    print(f"  Message: {messages[0].content}")
    print(f"  Max tokens: {request.max_tokens}")
    print("\nSending request...")

    try:
        response = await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model=model,
        )

        print("\nResponse received!")
        print("-" * 40)

        # Extract content from response
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, dict):
                choices = content.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    assistant_content = message.get("content", "")
                    print(f"Assistant: {assistant_content}")

                usage = content.get("usage", {})
                if usage:
                    print("\nUsage:")
                    print(f"  Prompt tokens: {usage.get('prompt_tokens', 'N/A')}")
                    print(
                        f"  Completion tokens: {usage.get('completion_tokens', 'N/A')}"
                    )
                    print(f"  Total tokens: {usage.get('total_tokens', 'N/A')}")
            else:
                print(f"Content: {content}")
        else:
            print(f"Response: {response}")

    except Exception as e:
        logger.error(f"Chat completion failed: {e}", exc_info=True)
        print(f"\nError: {e}")


async def main() -> None:
    """Main demo function."""
    print("=" * 60)
    print("Antigravity Backend Demo")
    print("=" * 60)
    print(f"\nEndpoint: {ANTIGRAVITY_SANDBOX_ENDPOINT}")
    print(f"User-Agent: {ANTIGRAVITY_USER_AGENT}")

    # Create the connector
    config = AppConfig()
    services = ServiceCollection()
    services.add_singleton(ITranslationService, TranslationService)
    provider = services.build_service_provider()
    translation_service = provider.get_required_service(ITranslationService)
    async with httpx.AsyncClient() as client:
        connector = GeminiOAuthAntigravityConnector(
            client=client,
            config=config,
            translation_service=translation_service,
        )

        # Initialize the connector
        print("\nInitializing connector...")
        await connector.initialize()

        if not connector.is_functional:
            print("\n[ERROR] Connector is not functional!")
            print("Please ensure:")
            print("  1. Antigravity app is installed")
            print("  2. You are authenticated in Antigravity")
            print("  3. The state database is accessible")
            if connector._credential_validation_errors:
                print("\nValidation errors:")
                for error in connector._credential_validation_errors:
                    print(f"  - {error}")
            return

        print("[OK] Connector initialized successfully!")

        # Demo 1: List models
        models = await demo_list_models(connector)

        if not models:
            print("\n[WARNING] No models found, skipping chat completion demo")
            return

        # Demo 2: Chat completion
        target_model = "gemini-2.5-flash-lite"
        if target_model not in models:
            print(
                f"\n[WARNING] {target_model} not available, using first available model"
            )
            target_model = models[0] if models else "gemini-2.5-flash"

        await demo_chat_completion(connector, target_model)

        print("\n" + "=" * 60)
        print("Demo completed!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
