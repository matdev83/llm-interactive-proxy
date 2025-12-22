#!/usr/bin/env python3
"""
Diagnostic script to analyze Antigravity backend request behavior.

This script helps diagnose why the proxy might be triggering rate limits
when native Antigravity works fine.

Usage:
    ./.venv/Scripts/python.exe scripts/diagnose_antigravity_rate_limit.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.services.translation_service import TranslationService

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def diagnose():
    """Run diagnostic checks on Antigravity backend."""
    import httpx

    print("=" * 60)
    print("Antigravity Backend Diagnostic")
    print("=" * 60)

    # Create connector
    async with httpx.AsyncClient(timeout=60.0) as client:
        config = AppConfig()

        # Setup DI container for TranslationService
        services = ServiceCollection()
        services.add_singleton(TranslationService)
        provider = services.build_service_provider()
        translation_service = provider.get_required_service(TranslationService)

        connector = AntigravityOAuthConnector(
            client=client,
            config=config,
            translation_service=translation_service,
        )

        # Check configuration
        print("\n--- Configuration ---")
        print(f"Backend type: {connector.backend_type}")
        print(f"API base URL: {connector.gemini_api_base_url}")
        print(f"Graceful degradation enabled: {connector._degradation_config.enabled}")
        print(
            f"Recovery probing enabled: {connector._degradation_config.enable_recovery_probing}"
        )

        # Check credentials
        print("\n--- Credentials ---")
        try:
            await connector.initialize()
            print(f"Credentials loaded: {bool(connector._oauth_credentials)}")
            if connector._oauth_credentials:
                print(
                    f"Has access token: {'access_token' in connector._oauth_credentials}"
                )
                print(f"Has project_id: {'project_id' in connector._oauth_credentials}")
        except Exception as e:
            print(f"Error loading credentials: {e}")
            return

        # Check request body builder
        print("\n--- Request Body Builder ---")
        print(f"Type: {type(connector._request_body_builder).__name__}")

        # Check endpoint config
        print("\n--- Endpoint Config ---")
        print(f"Type: {type(connector._endpoint_config).__name__}")

        # Check session headers
        print("\n--- Session Headers ---")
        headers = connector._get_session_headers()
        for k, v in headers.items():
            print(f"  {k}: {v}")

        # Build a sample request body to see the structure
        print("\n--- Sample Request Body Structure ---")
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        sample_request = CanonicalChatRequest(
            model="gemini-3-pro-high",
            messages=[ChatMessage(role="user", content="Hello, test message")],
            stream=True,
        )

        # Convert to inner request format
        gemini_request = translation_service.from_domain_to_gemini_request(
            sample_request
        )
        print(f"Gemini request keys: {list(gemini_request.keys())}")

        contents = gemini_request.get("contents", [])
        print(f"Contents count: {len(contents)}")
        if contents:
            total_chars = sum(
                len(part.get("text", ""))
                for content in contents
                for part in content.get("parts", [])
            )
            print(f"Total content chars: {total_chars}")

        # Build the wrapped request body
        inner_request = {
            "contents": contents,
            "generationConfig": gemini_request.get("generationConfig", {}),
        }

        wrapped_body = connector._request_body_builder.build(
            effective_model="gemini-3-pro-high",
            project_id="test-project",
            request_data=sample_request,
            inner_request=inner_request,
        )

        print(f"Wrapped body keys: {list(wrapped_body.keys())}")

        # Calculate size
        body_json = json.dumps(wrapped_body)
        print(f"Request body size: {len(body_json)} bytes")

        # Show the structure (truncated)
        print("\n--- Request Body Preview (truncated) ---")
        preview = json.dumps(wrapped_body, indent=2)[:1000]
        print(preview)
        if len(json.dumps(wrapped_body, indent=2)) > 1000:
            print("... (truncated)")

        print("\n" + "=" * 60)
        print("Diagnostic complete")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(diagnose())
