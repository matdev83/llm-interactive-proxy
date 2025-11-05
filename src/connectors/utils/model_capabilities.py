"""Model capability registry for hybrid backend.

This module provides centralized knowledge about model capabilities and
reasoning parameters for different LLM backends. It supports the hybrid
backend's adaptive placement strategy and reasoning parameter management.
"""

from typing import Any

# Models that support system messages
SYSTEM_MESSAGE_SUPPORT: dict[str, bool] = {
    "openai": True,
    "anthropic": True,
    "qwen": True,
    "qwen-oauth": True,
    "deepseek": True,
    "minimax": True,
    "openrouter": True,  # Most models on OpenRouter support system
    "gemini": False,  # Gemini uses different system instruction mechanism
    "gemini-oauth-free": False,
    "gemini-oauth-plan": False,
    "gemini-cli-acp": False,
    "gemini-cloud-project": False,
}

# Preferred reasoning tag format by backend
REASONING_TAG_FORMAT: dict[str, tuple[str, str]] = {
    "openai": ("<thinking>", "</thinking>"),
    "anthropic": ("<thinking>", "</thinking>"),
    "qwen": ("<thinking>", "</thinking>"),
    "qwen-oauth": ("<thinking>", "</thinking>"),
    "deepseek": ("<think>", "</think>"),  # DeepSeek uses <think> natively
    "minimax": ("<think>", "</think>"),
    "gemini": ("<thinking>", "</thinking>"),
    "gemini-oauth-plan": ("<thinking>", "</thinking>"),
    "gemini-oauth-free": ("<thinking>", "</thinking>"),
    "gemini-cli-acp": ("<thinking>", "</thinking>"),
    "gemini-cli-cloud-project": ("<thinking>", "</thinking>"),
    # Default for others
    "_default": ("<reasoning>", "</reasoning>"),
}

# Reasoning phase parameters - maximize reasoning quality
REASONING_PHASE_PARAMS: dict[str, dict[str, Any]] = {
    "openai": {
        "reasoning_effort": "high",
        # OpenAI o1 models use reasoning_effort
    },
    "qwen": {
        "thinking_budget": 10000,  # Maximum thinking tokens
        # Qwen models use thinking_budget
    },
    "qwen-oauth": {
        "thinking_budget": 10000,
    },
    "deepseek": {
        "reasoning_effort": "high",
        # DeepSeek R1 models use reasoning_effort
    },
    "minimax": {
        # MiniMax models have native reasoning, no override needed
    },
    "_default": {
        # Generic reasoning parameters
        "temperature": 0.7,  # Balanced for reasoning
        "reasoning_effort": "high",  # Ensure strong reasoning on unknown backends
    },
}

# Execution phase parameters - minimize redundant reasoning, maximize speed
EXECUTION_PHASE_PARAMS: dict[str, dict[str, Any]] = {
    "openai": {
        "reasoning_effort": "low",  # Minimal reasoning
    },
    "qwen": {
        "thinking_budget": 0,  # Disable thinking
    },
    "qwen-oauth": {
        "thinking_budget": 0,
    },
    "deepseek": {
        "reasoning_effort": "low",
    },
    "minimax": {
        # MiniMax models: cannot disable reasoning, use low temperature
        "temperature": 0.3,
    },
    "_default": {
        # Generic execution parameters
        "temperature": 0.5,  # Lower for consistency
        "reasoning_effort": "low",  # Minimize reasoning for unknown backends
    },
}


def supports_system_messages(backend: str) -> bool:
    """Check if backend supports system role messages.

    Args:
        backend: Backend name (e.g., "openai", "anthropic", "gemini")

    Returns:
        True if backend supports system messages, False otherwise.
        Defaults to True for unknown backends.
    """
    return SYSTEM_MESSAGE_SUPPORT.get(backend, True)


def get_reasoning_tags(backend: str) -> tuple[str, str]:
    """Get reasoning tags for backend.

    Args:
        backend: Backend name (e.g., "openai", "deepseek")

    Returns:
        Tuple of (opening_tag, closing_tag) for reasoning output.
        Returns default tags for unknown backends.
    """
    return REASONING_TAG_FORMAT.get(backend, REASONING_TAG_FORMAT["_default"])


def get_reasoning_params(backend: str) -> dict[str, Any]:
    """Get reasoning phase parameters for backend.

    These parameters maximize reasoning quality by enabling high reasoning
    effort or thinking budget.

    Args:
        backend: Backend name (e.g., "openai", "qwen")

    Returns:
        Dictionary of parameters to override for reasoning phase.
        Returns default parameters for unknown backends.
    """
    return REASONING_PHASE_PARAMS.get(
        backend, REASONING_PHASE_PARAMS["_default"]
    ).copy()


def get_execution_params(backend: str) -> dict[str, Any]:
    """Get execution phase parameters for backend.

    These parameters minimize redundant reasoning and maximize execution
    speed by disabling or reducing reasoning effort.

    Args:
        backend: Backend name (e.g., "openai", "qwen")

    Returns:
        Dictionary of parameters to override for execution phase.
        Returns default parameters for unknown backends.
    """
    return EXECUTION_PHASE_PARAMS.get(
        backend, EXECUTION_PHASE_PARAMS["_default"]
    ).copy()
