"""Constants for backend identifiers.

This module contains constants for backend identifiers to make tests
less fragile and more maintainable.
"""

# Backend types
BACKEND_OPENAI = "openai"
BACKEND_ANTHROPIC = "anthropic"
BACKEND_GEMINI = "gemini"
BACKEND_OPENROUTER = "openrouter"
BACKEND_QWEN_OAUTH = "qwen-oauth"
BACKEND_ZAI = "zai"

# Backend display names
# Display names removed to minimize public surface; use backend type constants instead.
# Note: Additional display names and prefixes have been removed to
# reduce the public surface area. Reintroduce as needed by callers.
