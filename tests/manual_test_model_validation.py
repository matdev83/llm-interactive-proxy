"""Quick test to verify model name validation in Antigravity connectors."""

import httpx
from src.connectors.anthropic_oauth_antigravity import (
    AnthropicOAuthAntigravityConnector,
)
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService

print("Testing model validation for Antigravity connectors...")

# Create connectors
client = httpx.AsyncClient()
config = AppConfig()
translation_service = TranslationService()

gemini_conn = AntigravityOAuthConnector(client, config, translation_service)
anthropic_conn = AnthropicOAuthAntigravityConnector(client, config, translation_service)

# Test 1: Gemini connector should accept Gemini models
print("\n1. Testing Gemini connector with gemini-2.0-flash...")
try:
    gemini_conn.validate_model("gemini-2.0-flash")
    print("   [OK] PASS: Gemini model accepted by Gemini connector")
except BackendError as e:
    print(f"   [FAIL] FAIL: {e.message}")

# Test 2: Gemini connector should reject Claude models
print("\n2. Testing Gemini connector with claude-sonnet-4-5...")
try:
    gemini_conn.validate_model("claude-sonnet-4-5")
    print("   [FAIL] FAIL: Claude model should have been rejected")
except BackendError as e:
    print(f"   [OK] PASS: Correctly rejected - {e.code}")

# Test 3: Anthropic connector should accept Claude models
print("\n3. Testing Anthropic connector with claude-sonnet-4-5...")
try:
    anthropic_conn.validate_model("claude-sonnet-4-5")
    print("   [OK] PASS: Claude model accepted by Anthropic connector")
except BackendError as e:
    print(f"   [FAIL] FAIL: {e.message}")

# Test 4: Anthropic connector should reject Gemini models
print("\n4. Testing Anthropic connector with gemini-2.0-flash...")
try:
    anthropic_conn.validate_model("gemini-2.0-flash")
    print("   [FAIL] FAIL: Gemini model should have been rejected")
except BackendError as e:
    print(f"   [OK] PASS: Correctly rejected - {e.code}")

print("\n[OK] All validation tests passed!")
