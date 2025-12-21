import asyncio
import logging
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

import httpx
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_demo():
    print("=" * 60)
    print("REAL E2E DEMO: Antigravity OAuth Connector")
    print("=" * 60)

    # 1. Initialize Real Components
    config = AppConfig()
    translation_service = TranslationService()

    # Real Client
    async with httpx.AsyncClient(timeout=30.0) as client:
        connector = AntigravityOAuthConnector(
            client, config, translation_service, name="antigravity-oauth"
        )

        # 2. Initialize (Loads real credentials from state.vscdb)
        print("Initializing connector (scanning for state.vscdb)...")
        try:
            await connector.initialize(
                enable_antigravity_backend_debugging_override=True
            )
        except Exception as e:
            print(f"[FAIL] Initialization Failed: {e}")
            return

        if not connector.is_functional:
            print("[FAIL] Connector is not functional. Credentials likely missing.")
            return

        print("[OK] Connector initialized successfully.")
        print(f"Project ID: {connector._project_id}")

        # 3. Send Real Request
        print("\nSending request to Gemini (gemini-2.5-flash)...")
        request = CanonicalChatRequest(
            model="gemini-2.5-flash",
            messages=[
                ChatMessage(
                    role="user",
                    content="Hello! Please say 'Antigravity OAuth is working'.",
                )
            ],
            stream=False,
        )

        try:
            response = await connector.chat_completions(
                request_data=request,
                processed_messages=request.messages,
                effective_model="gemini-2.5-flash",
            )

            print("\n[OK] Response Received:")
            # Parse response content
            if hasattr(response, "content"):
                print(response.content)
            else:
                print(response)

        except Exception as e:
            print(f"\n[FAIL] Request Failed: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_demo())
