from __future__ import annotations

import logging
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.core.domain.backend_capability_descriptor import BackendCapabilityDescriptor
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.interfaces.model_bases import DomainModel

DEFAULT_INTERLEAVED_THINKING_INSTRUCTIONS_FILE = (
    "config/prompts/interleaved_thinking/thinker_prompt.md"
)


def get_openrouter_headers(cfg: dict[str, str], api_key: str) -> dict[str, str]:
    """Construct headers for OpenRouter requests.

    Be tolerant of minimal cfg dicts provided by tests by falling back to
    sensible defaults when optional keys are absent.
    """

    referer: str = cfg.get("app_site_url", "http://localhost:8000")
    x_title: str = cfg.get("app_x_title", "InterceptorProxy")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": x_title,
    }


class BackendConfig(DomainModel):
    """Configuration for a backend service."""

    model_config = ConfigDict(frozen=True)

    api_key: str | None = None
    api_url: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout: int = 120  # seconds
    identity: AppIdentityConfig | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    allow_concurrent_use: bool = True
    credentials_path: str | None = None
    supported_input_types: list[str] | None = None
    connector: str | None = None
    capability_descriptor: BackendCapabilityDescriptor | None = None

    @field_validator("capability_descriptor", mode="before")
    @classmethod
    def validate_capability_descriptor(
        cls, v: Any
    ) -> BackendCapabilityDescriptor | None:
        """Coerce a plain dict into BackendCapabilityDescriptor."""
        if v is None:
            return None
        if isinstance(v, BackendCapabilityDescriptor):
            return v
        if isinstance(v, dict):
            return BackendCapabilityDescriptor.from_dict(v)
        return cast(BackendCapabilityDescriptor, v)

    @field_validator("supported_input_types", mode="before")
    @classmethod
    def validate_input_types(cls, v: Any) -> list[str] | None:
        """Validate input types against known multimodal types."""
        if v is None:
            return None

        from src.core.domain.multimodal_types import MultimodalInputType

        if isinstance(v, str):
            v = [v]

        if not isinstance(v, list):
            return []

        valid_types = [t.value for t in MultimodalInputType]
        result = []
        for item in v:
            if item in valid_types:
                result.append(item)
            elif item.lower() in valid_types:
                result.append(item.lower())

        return result

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, v: Any) -> str | None:
        """Ensure api_key is always a string or None."""
        if isinstance(v, list) and v:
            return str(v[0])
        if isinstance(v, list) and not v:
            return None
        return str(v) if v is not None else None

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str | None) -> str | None:
        """Validate the API URL if provided."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("API URL must start with http:// or https://")
        return v


class BackendSettings(DomainModel):
    """Settings for all backends.

    Immutable aggregate of declared settings plus dynamically named
    ``BackendConfig`` entries (extra fields).  Use ``model_copy(update=...)``
    to add or replace a backend configuration.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    default_backend: str = "openai"
    static_route: str | None = None
    disable_gemini_oauth_fallback: bool = False
    disable_gemini_oauth_reasoning_prompt_injection: bool = False
    disable_hybrid_backend: bool = False
    hybrid_backend_repeat_messages: bool = False
    reasoning_injection_probability: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Probability of using the reasoning model for a request in the hybrid backend.",
    )
    hybrid_reasoning_model_timeout: int = Field(
        default=60,
        ge=1,
        description="Timeout in seconds for the reasoning model call in hybrid scenarios. Defaults to 60.",
    )
    hybrid_reasoning_force_initial_turns: int = Field(
        default=1,
        ge=0,
        description="Number of turns at the beginning of a new session when the reasoning model probability is overridden to 1 (100%). Defaults to 1.",
    )
    hybrid_execution_model_timeout: int = Field(
        default=120,
        ge=1,
        description="Timeout in seconds for execution model call in hybrid scenarios. Defaults to 120.",
    )
    hybrid_reasoning_latency_threshold: float = Field(
        default=8.0,
        ge=0.0,
        description="Latency threshold (seconds) that triggers adaptive reasoning backoff when exceeded. Set 0 to disable.",
    )
    hybrid_reasoning_backoff_turns: int = Field(
        default=2,
        ge=0,
        description="Number of subsequent turns to skip reasoning after latency threshold is exceeded. Set 0 to disable adaptive backoff.",
    )
    interleaved_thinking_instructions_file: str | None = Field(
        default=DEFAULT_INTERLEAVED_THINKING_INSTRUCTIONS_FILE,
        description="Path to a file containing instructions injected only into [thinker] routed requests.",
    )

    @model_validator(mode="before")
    @classmethod
    def _assemble_dynamic_backends(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        from src.core.config.constrained_backend_policy import (
            match_constrained_connector_family,
        )

        raw = dict(data)
        known_fields = set(cls.model_fields.keys())
        init_data = {k: v for k, v in raw.items() if k in known_fields}
        backend_data = {k: v for k, v in raw.items() if k not in known_fields}

        claimed_constrained_families: set[str] = set()
        for existing_name in backend_data:
            family = match_constrained_connector_family(existing_name)
            if family and "." in existing_name:
                claimed_constrained_families.add(family)

        for backend_name in list(backend_data.keys()):
            family = match_constrained_connector_family(backend_name)
            if (
                family
                and family in claimed_constrained_families
                and backend_name.replace("_", "-") == family
            ):
                logger = logging.getLogger(__name__)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Dropping legacy backend configuration %r because instance "
                        "of %r already exists.",
                        backend_name,
                        family,
                    )
                del backend_data[backend_name]

        merged: dict[str, BackendConfig] = {}
        for backend_name, config_data in backend_data.items():
            if isinstance(config_data, dict):
                merged[backend_name] = BackendConfig(**config_data)
            elif isinstance(config_data, BackendConfig):
                merged[backend_name] = config_data

        from src.core.services.backend_registry import backend_registry

        registered_backends = backend_registry.get_registered_backends()
        for backend_name in registered_backends:
            if backend_name in merged:
                continue
            family = match_constrained_connector_family(backend_name)
            if family and family in claimed_constrained_families:
                continue
            merged[backend_name] = BackendConfig()

        return {**init_data, **merged}

    def get_named_backend_configs(self) -> dict[str, BackendConfig]:
        """Return dynamically configured backends (``name`` -> ``BackendConfig``)."""
        extra = getattr(self, "__pydantic_extra__", None) or {}
        return {k: v for k, v in extra.items() if isinstance(v, BackendConfig)}

    def __getitem__(self, key: str) -> BackendConfig:
        """Allow dictionary-style access to backend configs."""
        cfg = self.get_named_backend_configs().get(key)
        if cfg is None:
            raise KeyError(f"Backend '{key}' not found")
        return cfg

    def __setitem__(self, key: str, value: BackendConfig) -> None:
        raise TypeError(
            "BackendSettings is immutable; use model_copy(update={...}) instead."
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-style get with default."""
        return self.get_named_backend_configs().get(key, default)

    def lookup(self, name: str) -> BackendConfig | None:
        """Return an existing BackendConfig by exact key, without side effects."""
        value = self.get_named_backend_configs().get(name)
        return value if isinstance(value, BackendConfig) else None

    @property
    def functional_backends(self) -> set[str]:
        """Get the set of functional backends (those with API keys)."""
        from src.core.services.backend_registry import (
            backend_registry,
        )

        functional: set[str] = set()
        registered = backend_registry.get_registered_backends()
        configs = self.get_named_backend_configs()
        for backend_name in registered:
            cfg = configs.get(backend_name)
            if isinstance(cfg, BackendConfig) and cfg.api_key:
                functional.add(backend_name)

        oauth_like: set[str] = set()
        for name in registered:
            if name.endswith("-oauth") or name.startswith("gemini-oauth"):
                oauth_like.add(name)
            if name == "gemini-cli-cloud-project":
                oauth_like.add(name)

        functional.update(oauth_like.intersection(set(registered)))

        for name, cfg in configs.items():
            if name == "default_backend" or name.startswith("_"):
                continue
            if isinstance(cfg, BackendConfig) and cfg.api_key:
                functional.add(name)
        return functional

    def model_is_functional(self, model_id: str) -> bool:
        """Check if a model is available in any functional backend."""
        if ":" not in model_id:
            return False

        backend_name, _ = model_id.split(":", 1)
        return backend_name in self.functional_backends
