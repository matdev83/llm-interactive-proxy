"""
Demo script to test the OpenCode Zen backend connector.

This script:
1. Creates an instance of OpencodeZenConnector
2. Initializes it with debugging override enabled
3. Submits prompts for completion (non-streaming and streaming)
4. Displays the results

Prerequisites:
- Must have run 'opencode auth login' to create credentials at:
  - Windows: %LOCALAPPDATA%\\opencode\\auth.json
  - Linux/Mac: ~/.local/share/opencode/auth.json
"""

import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.getcwd())

import httpx
from src.connectors.opencode_zen import OpencodeZenConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d %(message)s",
)
logger = logging.getLogger(__name__)


async def test_opencode_zen():
    """Test the OpenCode Zen connector functionality."""
    print("=" * 80)
    print("DEMO: OpenCode Zen Backend Connector")
    print("=" * 80)
    print()

    # Initialize components
    print("[1] Initializing components...")
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=30.0))
    config = AppConfig()
    translation_service = TranslationService()

    connector = OpencodeZenConnector(
        client=client, config=config, translation_service=translation_service
    )

    try:
        # Step 2: Initialize connector
        print("\n[2] Initializing OpenCode Zen connector...")
        print("    Looking for credentials at default location...")

        try:
            await connector.initialize(
                enable_opencode_zen_backend_debugging_override=True
            )
        except Exception as e:
            print(f"\n[FAIL] Failed to initialize connector: {e}")
            return

        if not connector.is_functional:
            errors = connector.get_validation_errors()
            print("\n[FAIL] Connector is not functional.")
            print("    Validation errors:")
            for error in errors:
                print(f"      - {error}")
            print()
            print("    Please ensure you have:")
            print("      1. Run 'opencode auth login' to authenticate")
            print("      2. The auth.json file exists in the correct location")
            return

        print("[OK] Connector initialized successfully!")
        print(f"    API Base URL: {connector.api_base_url}")
        print(f"    Available models: {len(connector.available_models)}")
        for model in connector.available_models[:5]:  # Show first 5 models
            print(f"      - {model}")
        if len(connector.available_models) > 5:
            print(f"      ... and {len(connector.available_models) - 5} more")

        # Step 3: Test non-streaming completion
        print("\n[3] Testing non-streaming completion...")
        model = (
            connector.available_models[0]
            if connector.available_models
            else "anthropic/claude-sonnet-4.5"
        )
        print(f"    Using model: {model}")

        request = CanonicalChatRequest(
            model=f"opencode-zen/{model}",
            messages=[
                ChatMessage(
                    role="user",
                    content="Say 'OpenCode Zen connector is working!' and add a short greeting.",
                )
            ],
            stream=False,
        )

        try:
            response = await connector.chat_completions(
                request_data=request,
                processed_messages=request.messages,
                effective_model=f"opencode-zen/{model}",
            )

            print("\n[OK] Response received!")

            # Extract and display content
            if hasattr(response, "content"):
                content = response.content
                if isinstance(content, dict):
                    choices = content.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {})
                        message_content = message.get("content", "")
                        print("\n    Response content:")
                        print(f'    "{message_content}"')

                    # Show usage if available
                    usage = content.get("usage", {})
                    if usage:
                        print("\n    Usage:")
                        print(
                            f"      Prompt tokens: {usage.get('prompt_tokens', 'N/A')}"
                        )
                        print(
                            f"      Completion tokens: {usage.get('completion_tokens', 'N/A')}"
                        )
                        print(f"      Total tokens: {usage.get('total_tokens', 'N/A')}")
                else:
                    print(f"    Response: {content}")

        except Exception as e:
            print(f"\n[FAIL] Non-streaming request failed: {e}")
            import traceback

            traceback.print_exc()

        # Step 4: Test streaming completion (optional)
        print("\n[4] Testing streaming completion...")
        print(f"    Using model: {model}")

        stream_request = CanonicalChatRequest(
            model=f"opencode-zen/{model}",
            messages=[
                ChatMessage(
                    role="user",
                    content="Count from 1 to 5 slowly.",
                )
            ],
            stream=True,
        )

        try:
            stream_response = await connector.chat_completions(
                request_data=stream_request,
                processed_messages=stream_request.messages,
                effective_model=f"opencode-zen/{model}",
            )

            print("\n[OK] Streaming response received!")
            print("    Streaming content: ", end="", flush=True)

            if hasattr(stream_response, "content"):
                chunk_count = 0
                async for chunk in stream_response.content:
                    chunk_count += 1
                    # Try to extract text from chunk
                    if isinstance(chunk, dict):
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                print(content, end="", flush=True)

                print()  # New line after streaming
                print(f"\n    Total chunks received: {chunk_count}")

        except Exception as e:
            print(f"\n[FAIL] Streaming request failed: {e}")
            import traceback

            traceback.print_exc()

        # Summary
        print("\n" + "=" * 80)
        print("DEMO COMPLETE")
        print("=" * 80)
        print()
        print("Summary:")
        print(
            f"  - Connector initialized: {'Yes' if connector.is_functional else 'No'}"
        )
        print(f"  - Models available: {len(connector.available_models)}")
        print(
            f"  - Debugging override enabled: {connector._enable_opencode_zen_backend_debugging_override}"
        )

    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(test_opencode_zen())
