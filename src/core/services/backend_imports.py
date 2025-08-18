"""Module that imports all connector modules to ensure backend registration.

This module should be imported at application startup to ensure all backend
connectors register themselves with the backend registry.
"""

# Import all connector modules to trigger backend registration
from src.connectors import anthropic, gemini, openai, openrouter, qwen_oauth, zai

__all__: list[str] = []