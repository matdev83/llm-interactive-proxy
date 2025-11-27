"""
Demo script to verify the gemini-oauth-antigravity backend works.

This script initializes the connector and makes a real API call to demonstrate
functionality.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.translation_service import TranslationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Main demo function. Returns exit code."""
    print("=" * 60)
    print("Antigravity Backend - claude-sonnet-4-5 Demo")
    print("=" * 60)

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
        print("\n[1/4] Initializing connector...")
        await connector.initialize()

        if not connector.is_functional:
            print("\n[ERROR] Connector is not functional!")
            print("Possible reasons:")
            print("  - Antigravity app is not installed or not logged in")
            print("  - OAuth credentials are missing or expired")
            return 1

        print("[OK] Connector initialized successfully!")

        # Check available models
        print("\n[2/4] Checking available models...")
        models = connector.get_available_models()
        print(f"[OK] Found {len(models)} available models")
        if "claude-sonnet-4-5" in models:
            print("[OK] claude-sonnet-4-5 is available!")
        else:
            print("[WARN] claude-sonnet-4-5 not in model list, but may still work")
            print(f"     Available: {models[:5]}...")

        # Create the request
        print("\n[3/4] Creating chat request...")
        messages = [
            ChatMessage(
                role="user",
                content="Hello! What is 2 + 2? Please respond with just the number.",
            )
        ]

        request = ChatRequest(
            model="claude-sonnet-4-5",
            messages=messages,
            max_tokens=50,
            temperature=0.1,
            stream=False,
        )

        print(f"  Model: {request.model}")
        print(f"  Prompt: {messages[0].content}")
        print(f"  Max tokens: {request.max_tokens}")

        # Send the request
        print("\n[4/4] Sending request to API...")
        try:
            response = await connector.chat_completions(
                request_data=request,
                processed_messages=request.messages,
                effective_model=request.model,
            )

            print("\n" + "=" * 60)
            print("SUCCESS! Response received:")
            print("=" * 60)

            # Extract content from response
            if hasattr(response, "content"):
                content = response.content
                if isinstance(content, str):
                    print(f"\nResponse: {content}")
                elif isinstance(content, dict):
                    # OpenAI format
                    choices = content.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {})
                        text = message.get("content", str(content))
                        print(f"\nResponse: {text}")
                    else:
                        print(f"\nRaw response: {content}")
                else:
                    print(f"\nRaw response: {content}")
            else:
                print(f"\nResponse object: {response}")

            if hasattr(response, "usage") and response.usage:
                print(f"\nUsage: {response.usage}")

            print("\n[SUCCESS] The gemini-oauth-antigravity backend is working!")
            return 0

        except Exception as e:
            print(f"\n[ERROR] Request failed: {e}")
            logger.error("Chat completion failed", exc_info=True)

            # Check if it's a quota error
            error_str = str(e).lower()
            if "429" in error_str or "quota" in error_str or "exhausted" in error_str:
                print("\n[INFO] This appears to be a quota/rate limit error.")
                print(
                    "       The backend IS working, but quota is temporarily exhausted."
                )
                print("       Wait for quota reset and try again.")
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
