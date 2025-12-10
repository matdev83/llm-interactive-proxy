import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.connectors.cline import ClineConnector
from src.core.config.app_config import AppConfig
from src.core.di.services import get_service_collection, register_core_services
from src.core.interfaces.translation_service_interface import ITranslationService

# Configure logging to see what's happening
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    print("--- Cline Connector Model List Demo ---")

    config = AppConfig()

    # Bootstrap DI
    services = get_service_collection()
    register_core_services(services, config)
    provider = services.build_service_provider()

    translation_service = provider.get_required_service(ITranslationService)

    async with httpx.AsyncClient() as client:
        connector = ClineConnector(
            client=client, config=config, translation_service=translation_service
        )

        try:
            print("1. Initializing connector (getting auth token)...")
            await connector.initialize()
            print(f"   Auth successful. Token: {connector.api_key[:10]}...")

            headers = connector.get_headers()

            # Try to fetch user info to get organization ID
            print("\n2. Fetching User Info...")
            user_info_url = "https://api.cline.bot/api/v1/users/me"
            user_response = await client.get(user_info_url, headers=headers)

            if user_response.status_code != 200:
                print(f"   Failed to fetch user info: {user_response.status_code}")
                print(f"   Body: {user_response.text}")
                return

            user_data = user_response.json().get("data", {})
            print(f"   User ID: {user_data.get('id')}")

            organizations = user_data.get("organizations", [])
            if not organizations:
                print("   No organizations found.")
                return

            print(f"   Found {len(organizations)} organizations.")

            # Find active organization or use first one
            org_id = None
            for org in organizations:
                if org.get("active"):
                    org_id = org.get("organizationId")
                    print(f"   Found active organization: {org.get('name')} ({org_id})")
                    break

            if not org_id:
                org_id = organizations[0].get("organizationId")
                print(
                    f"   Using first organization: {organizations[0].get('name')} ({org_id})"
                )

            # Fetch remote config
            print(f"\n3. Fetching Remote Config for Organization {org_id}...")
            remote_config_url = (
                f"https://api.cline.bot/api/v1/organizations/{org_id}/remote-config"
            )
            config_response = await client.get(remote_config_url, headers=headers)

            if config_response.status_code != 200:
                print(
                    f"   Failed to fetch remote config: {config_response.status_code}"
                )
                print(f"   Body: {config_response.text}")
                return

            config_wrapper = config_response.json()
            if not config_wrapper.get("success"):
                print(f"   API Error: {config_wrapper.get('error')}")
                return

            config_data = config_wrapper.get("data", {})
            if not config_data.get("enabled"):
                print("   Remote config is disabled.")
                return

            raw_value = config_data.get("value")
            if not raw_value:
                print("   No config value found.")
                return

            try:
                parsed_config = json.loads(raw_value)
                print("\n4. Parsed Remote Config:")

                provider_settings = parsed_config.get("providerSettings", {})
                cline_settings = provider_settings.get("Cline", {})
                models = cline_settings.get("models", [])

                if models:
                    print(f"   Found {len(models)} Cline models:")
                    for model in models:
                        print(f"   • {model.get('id')}")
                else:
                    print("   No specific Cline models found in remote config.")

                # Also check OpenAiCompatible models just in case
                openai_settings = provider_settings.get("OpenAiCompatible", {})
                openai_models = openai_settings.get("models", [])
                if openai_models:
                    print(f"\n   Found {len(openai_models)} OpenAI-Compatible models:")
                    for model in openai_models:
                        print(f"   • {model.get('id')}")

            except json.JSONDecodeError as e:
                print(f"   Failed to parse config JSON: {e}")

        except Exception as e:
            print(f"\n[ERROR] Initialization failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
