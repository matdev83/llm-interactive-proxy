"""Test script for antigravity-oauth connector with Claude model."""

import asyncio
import logging

import httpx
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


async def run_demo():
    """Demonstrate antigravity-oauth with Claude model."""
    print("=" * 60)
    print("REAL E2E DEMO: Antigravity OAuth Connector (Claude)")
    print("=" * 60)

    # Create connector
    config = AppConfig()
    translation_service = TranslationService()
    client = httpx.AsyncClient()

    connector = AntigravityOAuthConnector(
        client=client, config=config, translation_service=translation_service
    )

    # Initialize
    print("Initializing connector (scanning for state.vscdb)...")
    await connector.initialize(enable_antigravity_backend_debugging_override=True)
    print("[OK] Connector initialized successfully.")
    print(f"Project ID: {connector._project_id}")

    # Test with Claude model
    print("\nSending request to Claude (claude-sonnet-4-5)...")

    from src.core.domain.chat import ChatMessage, ChatRequest

    request_data = ChatRequest(
        model="claude-sonnet-4-5",
        messages=[
            ChatMessage(role="user", content="Say 'Claude Antigravity is working.'")
        ],
        stream=False,
    )

    try:
        response = await connector.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model="claude-sonnet-4-5",
        )

        print("\n[OK] Response Received:")
        if hasattr(response, "content"):
            if hasattr(response.content, "choices"):
                print(response.content.choices[0].message.content)
            else:
                print(response.content)
        else:
            print(response)
    except Exception as e:
        print(f"\n[FAIL] Request Failed: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(run_demo())
