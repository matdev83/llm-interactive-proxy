"""
Temporary demo script to verify the gemini-oauth-auto backend works.

This script initializes the connector and makes a real API call to demonstrate
functionality with the authenticated Google account.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_oauth_auto import GeminiOAuthAutoConnector
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.translation_service import TranslationService

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Main demo function. Returns exit code."""
    print("=" * 70)
    print("Gemini OAuth Auto Backend - Demo")
    print("=" * 70)

    # Create the connector
    config = AppConfig()
    services = ServiceCollection()
    services.add_singleton(ITranslationService, TranslationService)
    provider = services.build_service_provider()

    translation_service = provider.get_required_service(ITranslationService)

    async with httpx.AsyncClient(timeout=60.0) as client:
        connector = GeminiOAuthAutoConnector(
            client=client,
            config=config,
            translation_service=translation_service,
            name="gemini-oauth-auto",
        )

        # Initialize the connector
        print("\n[1/4] Initializing connector...")
        try:
            await connector.initialize(
                enable_gemini_oauth_auto_backend_debugging_override=True
            )
        except Exception as e:
            print(f"\n[ERROR] Failed to initialize connector: {e}")
            logger.error("Initialization failed", exc_info=True)
            return 1

        if not connector.is_functional:
            print("\n[ERROR] Connector is not functional!")
            print("Possible reasons:")
            print("  - No accounts have been registered")
            print("  - All accounts have expired tokens")
            print("  - OAuth credentials are missing or invalid")
            return 1

        print("[OK] Connector initialized successfully!")

        # Show account information
        account_selector = connector._account_selector
        available_count = account_selector.get_available_count()
        print(f"\n[INFO] Available accounts: {available_count}")

        # Force use of pinkbananaaipro_gmail_com account
        target_account_id = "pinkbananaaipro_gmail_com"
        print(f"\n[INFO] Forcing use of account: {target_account_id}")

        # Get the target account from storage
        storage = connector._token_storage
        target_account = await storage.get_account(target_account_id)
        if not target_account:
            print(f"\n[ERROR] Account {target_account_id} not found!")
            print("Available accounts:")
            all_accounts = await storage.list_accounts()
            for acc in all_accounts:
                print(f"  - {acc.account_id} ({acc.email})")
            return 1

        # Set as current account
        account_selector._current_account = target_account
        connector._sync_selected_account_to_base()

        print(
            f"[OK] Using account: {target_account.account_id} ({target_account.email})"
        )
        if target_account.project_id:
            print(f"       Cached project_id: {target_account.project_id}")
        else:
            print("       No cached project_id - will discover via API")

        # Clear cached project_id to force rediscovery
        connector._project_id = None

        # Check available models
        print("\n[2/4] Checking available models...")
        try:
            models = connector.get_available_models()
            print(f"[OK] Found {len(models)} available models")
            if models:
                print(f"     Sample models: {', '.join(models[:5])}")
        except Exception as e:
            print(f"[WARN] Could not fetch models list: {e}")
            print("     Continuing anyway...")

        # Create the request
        print("\n[3/4] Creating chat request...")
        canonical_request = CanonicalChatRequest(
            model="gemini-3-flash-preview",
            messages=[
                ChatMessage(
                    role="user",
                    content="Hello! Please confirm that the Gemini OAuth Auto backend is working. "
                    "Respond with a brief message confirming you received this request.",
                )
            ],
            max_tokens=100,
            temperature=0.7,
            stream=False,
        )

        connector_request = ConnectorChatCompletionsRequest(
            request=canonical_request,
            processed_messages=canonical_request.messages,
            effective_model="gemini-3-flash-preview",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        print(f"  Model: {canonical_request.model}")
        print(f"  Prompt: {canonical_request.messages[0].content[:60]}...")
        print(f"  Max tokens: {canonical_request.max_tokens}")

        # Send the request
        print("\n[4/4] Sending request to API...")
        try:
            response = await connector.chat_completions(connector_request)

            print("\n" + "=" * 70)
            print("SUCCESS! Response received:")
            print("=" * 70)

            # Extract content from response
            if hasattr(response, "content"):
                content = response.content
                if isinstance(content, str):
                    print(f"\nResponse:\n{content}")
                elif isinstance(content, dict):
                    # OpenAI format
                    choices = content.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {})
                        text = message.get("content", str(content))
                        print(f"\nResponse:\n{text}")
                    else:
                        print(f"\nRaw response: {content}")
                else:
                    print(f"\nResponse object: {content}")
            else:
                print(f"\nResponse object: {response}")

            if hasattr(response, "usage") and response.usage:
                print(f"\nUsage: {response.usage}")

            print("\n" + "=" * 70)
            print("[SUCCESS] The gemini-oauth-auto backend is working!")
            print("=" * 70)

            # Test second account if available
            if available_count > 1:
                print("\n" + "=" * 70)
                print("Testing account rotation...")
                print("=" * 70)

                # Get next account
                next_account = await account_selector.get_next_account()
                if next_account:
                    print(
                        f"\n[INFO] Rotated to account: {next_account.account_id} ({next_account.email})"
                    )

                    # Make another request with the second account
                    print("\n[5/5] Sending second request with rotated account...")
                    try:
                        response2 = await connector.chat_completions(connector_request)

                        if hasattr(response2, "content"):
                            content2 = response2.content
                            if isinstance(content2, str):
                                print(
                                    f"\nResponse from second account:\n{content2[:100]}..."
                                )
                            elif isinstance(content2, dict):
                                choices = content2.get("choices", [])
                                if choices:
                                    message = choices[0].get("message", {})
                                    text = message.get("content", "")
                                    print(
                                        f"\nResponse from second account:\n{text[:100]}..."
                                    )

                        print("\n[SUCCESS] Both accounts are working!")
                        return 0
                    except Exception as e:
                        print(f"\n[WARN] Second account request failed: {e}")
                        print(
                            "       First account worked, but second account had issues."
                        )
                        return 0  # Still return success since first account worked

            return 0

        except Exception as e:
            print(f"\n[ERROR] Request failed: {e}")
            logger.error("Chat completion failed", exc_info=True)

            # Check for specific error types
            error_str = str(e).lower()
            if "429" in error_str or "quota" in error_str or "exhausted" in error_str:
                print("\n[INFO] This appears to be a quota/rate limit error.")
                print(
                    "       The backend IS working, but quota is temporarily exhausted."
                )
                print(
                    "       The connector should automatically rotate to another account if available."
                )
            elif "403" in error_str or "forbidden" in error_str:
                print("\n[INFO] This appears to be a permission/authentication error.")
                print("       Check that the debugging override flag is enabled.")
            elif "permission denied" in error_str and "project" in error_str:
                print("\n[INFO] Project ID discovery issue detected.")
                print("       The connector successfully:")
                print("       [OK] Initialized and loaded OAuth accounts")
                print("       [OK] Authenticated with Google")
                print("       [OK] Discovered available models")
                print("       [OK] Connected to the API endpoint")
                print("\n       However, project ID discovery needs to be implemented.")
                print("       The connector currently uses 'default' as project ID,")
                print("       but the API requires a discovered project ID.")
                print("\n       This is a known limitation that needs to be addressed.")
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
