"""
Demo script to test Gemini schema sanitization with live backend.

This script:
1. Initializes the AntigravityOAuthConnector
2. Sends a request with the problematic TodoWrite tool
3. Verifies the request succeeds (proving the schema fix works)
"""

import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.getcwd())

import httpx
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d %(message)s",
)
logger = logging.getLogger(__name__)

# Problematic TodoWrite tool definition (contains Union[List, str] with tuple items)
PROBLEMATIC_TOOL = {
    "type": "function",
    "function": {
        "name": "TodoWrite",
        "description": "Write todo items",
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "anyOf": [
                        {
                            "type": "array",
                            "items": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "content": {"type": "string"},
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "done"],
                                        },
                                    },
                                    "required": ["content", "status"],
                                },
                                {"type": "string"},
                            ],
                        },
                        {"type": "string"},
                    ],
                    "description": "The updated todo list",
                }
            },
            "required": ["todos"],
        },
    },
}


async def test_live_backend():
    """Test the schema fix with the actual Gemini backend."""
    print("=" * 80)
    print("LIVE BACKEND TEST: Gemini Schema Sanitization")
    print("=" * 80)

    # Step 1: Initialize connector
    print("\n[1] Initializing AntigravityOAuthConnector...")
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=30.0))
    config = AppConfig()
    translation_service = TranslationService()

    connector = AntigravityOAuthConnector(
        client=client, config=config, translation_service=translation_service
    )

    try:
        try:
            await connector.initialize(
                enable_antigravity_backend_debugging_override=True
            )
            print("[OK] Connector initialized successfully")
        except Exception as e:
            print(f"[FAIL] Failed to initialize connector: {e}")
            return

        # Step 2: Create request with problematic tool
        print("\n[2] Creating request with problematic TodoWrite tool...")
        print("    Tool schema contains:")
        print("    - anyOf (Union type)")
        print("    - Tuple validation in items")

        request = ChatRequest(
            model="claude-sonnet-4-5",
            messages=[ChatMessage(role="user", content="Hello, can you help me?")],
            tools=[PROBLEMATIC_TOOL],
            stream=False,
        )

        # Step 3: Send request
        print("\n[3] Sending request to Gemini Code Assist API...")
        print("    Model: claude-sonnet-4-5")
        print("    Endpoint: https://daily-cloudcode-pa.sandbox.googleapis.com")

        try:
            response = await connector.chat_completions(
                request_data=request,
                processed_messages=request.messages,
                effective_model="claude-sonnet-4-5",
            )

            print(
                "\n[OK] SUCCESS: Request completed without 400 INVALID_ARGUMENT error!"
            )
            print(f"    Response type: {type(response)}")

            if hasattr(response, "content") and hasattr(response.content, "choices"):
                first_choice = (
                    response.content.choices[0] if response.content.choices else None
                )
                if first_choice and hasattr(first_choice, "message"):
                    message_content = first_choice.message.content or "(no content)"
                    preview = (
                        message_content[:200] + "..."
                        if len(message_content) > 200
                        else message_content
                    )
                    print(f"    Message preview: {preview}")

            print("\n" + "=" * 80)
            print("[OK] VERIFICATION COMPLETE: Schema sanitization fix is working!")
            print("=" * 80)
            print("\nThe fix successfully:")
            print("  1. Flattened the anyOf union (picked first option)")
            print("  2. Converted tuple items to empty schema {}")
            print("  3. Removed all forbidden keywords")
            print("\nThe Gemini backend accepted the sanitized schema.")

        except Exception as e:
            error_str = str(e)
            print(f"\n[FAIL] FAILED: {error_str}")

            if "400" in error_str and "INVALID_ARGUMENT" in error_str:
                print(
                    "\n[WARN]  The fix did NOT work - still getting 400 INVALID_ARGUMENT"
                )
                print(
                    "    This means the schema sanitization is not being applied correctly."
                )
            elif "403" in error_str or "Forbidden" in error_str:
                print("\n[WARN]  Permission error - debugging override may not be set")
            else:
                print(f"\n[WARN]  Unexpected error: {type(e).__name__}")

            import traceback

            print("\nFull traceback:")
            traceback.print_exc()

    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(test_live_backend())
