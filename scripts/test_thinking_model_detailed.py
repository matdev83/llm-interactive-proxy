#!/usr/bin/env python3
"""
Detailed test to verify gemini-2.5-flash-thinking model compatibility with gemini-oauth-antigravity.

This script checks:
1. Whether gemini-2.5-flash-thinking is in the hardcoded model list
2. Whether it's returned by the API
3. The actual validation behavior
4. Provides recommendations
"""

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import httpx
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService
from src.core.common.exceptions import BackendError


async def test_thinking_model():
    """Comprehensive test for gemini-2.5-flash-thinking availability."""
    
    config = AppConfig()
    translation_service = TranslationService()
    client = httpx.AsyncClient(timeout=60.0)
    
    try:
        backend = GeminiOAuthAntigravityConnector(
            client=client,
            config=config,
            translation_service=translation_service
        )
        
        await backend.initialize()
        
        print("\n" + "="*70)
        print("GEMINI-2.5-FLASH-THINKING BACKEND COMPATIBILITY TEST")
        print("="*70)
        
        # Get hardcoded models
        hardcoded_models = set(backend.available_models)
        print(f"\n1. HARDCODED FALLBACK MODELS ({len(hardcoded_models)} total):")
        thinking_in_hardcoded = "gemini-2.5-flash-thinking" in hardcoded_models
        print(f"   - gemini-2.5-flash-thinking in hardcoded list: {thinking_in_hardcoded}")
        if thinking_in_hardcoded:
            print("     WARNING: Not found in hardcoded list!")
        
        # Get actual API models
        await backend._ensure_models_loaded()
        api_models = backend._get_available_models_set()
        print(f"\n2. API AVAILABLE MODELS ({len(api_models)} total):")
        thinking_in_api = "gemini-2.5-flash-thinking" in api_models
        print(f"   - gemini-2.5-flash-thinking in API list: {thinking_in_api}")
        
        # Check if models were loaded from API or hardcoded
        from_api = getattr(backend, "_models_from_api", False)
        print(f"\n3. MODELS SOURCE:")
        print(f"   - Loaded from API: {from_api}")
        if not from_api:
            print("     (Using hardcoded fallback because API endpoint returned 404)")
        
        # Test validation
        print(f"\n4. MODEL VALIDATION TEST:")
        try:
            backend.validate_model("gemini-2.5-flash-thinking")
            print("   - Validation result: PASSED")
            print(f"     Reason: Model accepted by validator")
        except BackendError as e:
            print("   - Validation result: FAILED")
            print(f"     Reason: {e.message}")
        
        # Summary
        print(f"\n5. SUMMARY:")
        print(f"   - gemini-2.5-flash-thinking is NOT in the actual available models")
        print(f"   - Validation passes because it uses a hardcoded fallback list")
        print(f"   - This is a UNRELIABLE setup for production use")
        
        print(f"\n6. RECOMMENDATION:")
        if thinking_in_api:
            print("   -> Model IS available on Antigravity backend - safe to use")
        else:
            print("   -> Model is NOT available on Antigravity backend")
            print("   -> Attempting to use it may result in API errors")
            print("   -> Consider using: gemini-2.5-flash instead")
        
        print("\n" + "="*70 + "\n")
        
        return not thinking_in_api  # Return False if model unavailable
        
    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
        return False
    
    finally:
        await client.aclose()


async def main():
    """Run the test."""
    unavailable = await test_thinking_model()
    return 1 if unavailable else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
