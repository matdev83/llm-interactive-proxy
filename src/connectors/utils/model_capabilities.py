"""Model capability registry for hybrid backend.

This module provides centralized knowledge about model capabilities and
reasoning parameters for different LLM backends. It supports the hybrid
backend's adaptive placement strategy and reasoning parameter management.
"""

from pydantic import BaseModel, Field
from pydantic.types import JsonValue

from typing import Any


class BackendParameters(BaseModel):
    """Strongly typed container for backend parameters.

    Represents a set of parameter overrides that can be applied to LLM
    requests (e.g., reasoning effort, thinking budget, temperature).
    Provides dict-like interface for backward compatibility with existing code.
    """

    reasoning_effort: str | None = Field(
        default=None,
        description="Reasoning effort level (e.g., 'high', 'low')",
    )
    thinking_budget: int | None = Field(
        default=None,
        description="Maximum thinking tokens budget",
    )
    temperature: float | None = Field(
        default=None,
        description="Temperature setting",
    )

    extra_params: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Additional backend-specific parameters",
    )

    def copy(self, **updates: Any) -> "BackendParameters":
        """Create a copy with field updates (backward compatible)."""
        data = self.model_dump()
        data.update(updates)
        data.pop("extra_params", None)
        for key, value in updates.items():
            if key not in self.model_fields:
                data.setdefault("extra_params", {})[key] = value
        return BackendParameters(**data)

    def items(self):
        """Iterate over all parameters (backward compatible)."""
        result = {}
        for field_name in self.model_fields:
            if field_name == "extra_params":
                continue
            value = getattr(self, field_name, None)
            if value is not None:
                result[field_name] = value
        result.update(self.extra_params)
        return result.items()

    def keys(self):
        """Get all parameter keys (backward compatible)."""
        result = set()
        for field_name in self.model_fields:
            if field_name == "extra_params":
                continue
            value = getattr(self, field_name, None)
            if value is not None:
                result.add(field_name)
        result.update(self.extra_params.keys())
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """Get parameter value (backward compatible)."""
        if key in self.model_fields and key != "extra_params":
            value = getattr(self, key, None)
            return value if value is not None else default
        return self.extra_params.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Get parameter value (backward compatible)."""
        if key in self.model_fields and key != "extra_params":
            value = getattr(self, key, None)
            if value is None:
                raise KeyError(key)
            return value
        if key in self.extra_params:
            return self.extra_params[key]
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        """Check if parameter exists (backward compatible)."""
        if not isinstance(key, str):
            return False
        if key in self.model_fields and key != "extra_params":
            return getattr(self, key, None) is not None
        return key in self.extra_params

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
    "antigravity-oauth": False,
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
    "antigravity-oauth": ("<thinking>", "</thinking>"),
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


def _dict_to_backend_params(data: dict[str, Any]) -> BackendParameters:
    """Convert dict to BackendParameters, separating known fields from extra."""
    known_fields = {}
    extra_params = {}
    for key, value in data.items():
        if key in BackendParameters.model_fields and key != "extra_params":
            known_fields[key] = value
        else:
            extra_params[key] = value
    return BackendParameters(**known_fields, extra_params=extra_params)


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


def get_reasoning_params(backend: str) -> BackendParameters:
    """Get reasoning phase parameters for backend.

    These parameters maximize reasoning quality by enabling high reasoning
    effort or thinking budget.

    Args:
        backend: Backend name (e.g., "openai", "qwen")

    Returns:
        BackendParameters instance with parameters for reasoning phase.
        Returns default parameters for unknown backends.
    """
    params_dict = REASONING_PHASE_PARAMS.get(
        backend, REASONING_PHASE_PARAMS["_default"]
    )
    return _dict_to_backend_params(params_dict)


def get_execution_params(backend: str) -> BackendParameters:
    """Get execution phase parameters for backend.

    These parameters minimize redundant reasoning and maximize execution
    speed by disabling or reducing reasoning effort.

    Args:
        backend: Backend name (e.g., "openai", "qwen")

    Returns:
        BackendParameters instance with parameters for execution phase.
        Returns default parameters for unknown backends.
    """
    params_dict = EXECUTION_PHASE_PARAMS.get(
        backend, EXECUTION_PHASE_PARAMS["_default"]
    )
    return _dict_to_backend_params(params_dict)
