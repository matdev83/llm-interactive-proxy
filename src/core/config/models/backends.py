from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator, model_serializer

from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.interfaces.model_bases import DomainModel
from src.core.services.backend_registry import backend_registry


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

    Note: This class is intentionally not frozen because it needs to support
    dynamic backend configurations that are added at runtime. Backend configs
    are stored in __dict__ to allow attribute-style access (e.g., config.backends.openai)
    without pre-defining all possible backends as fields.
    """

    model_config = ConfigDict(frozen=False, extra="allow")

    default_backend: str = "openai"
    static_route: str | None = None
    disable_gemini_oauth_fallback: bool = False
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

    def __init__(self, **data: Any) -> None:
        # Access model_fields on the class (Pydantic >=2.11 deprecates instance access)
        known_fields = set(type(self).model_fields.keys())

        init_data = {k: v for k, v in data.items() if k in known_fields}
        backend_data = {k: v for k, v in data.items() if k not in known_fields}

        super().__init__(**init_data)

        for backend_name, config_data in backend_data.items():
            if isinstance(config_data, dict):
                self.__dict__[backend_name] = BackendConfig(**config_data)
            elif isinstance(config_data, BackendConfig):
                self.__dict__[backend_name] = config_data

        registered_backends = backend_registry.get_registered_backends()
        for backend_name in registered_backends:
            if backend_name not in self.__dict__:
                self.__dict__[backend_name] = BackendConfig()

        self._initialization_complete = True

    def __getitem__(self, key: str) -> BackendConfig:
        """Allow dictionary-style access to backend configs."""
        if key in self.__dict__:
            return cast(BackendConfig, self.__dict__[key])
        raise KeyError(f"Backend '{key}' not found")

    def __setitem__(self, key: str, value: BackendConfig) -> None:
        """Allow dictionary-style setting of backend configs."""
        self.__dict__[key] = value

    def __setattr__(self, name: str, value: Any) -> None:
        """Allow attribute-style assignment for backend configs."""
        if (
            name in {"default_backend"}
            or name.startswith("_")
            or name in type(self).model_fields
        ):
            super().__setattr__(name, value)
            return
        if isinstance(value, BackendConfig):
            config = value
        elif isinstance(value, dict):
            config = BackendConfig(**value)
        else:
            config = BackendConfig()
        self.__dict__[name] = config

    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-style get with default."""
        return cast(BackendConfig | None, self.__dict__.get(key, default))

    def lookup(self, name: str) -> BackendConfig | None:
        """Return an existing BackendConfig by exact key, without side effects."""
        value = self.__dict__.get(name)
        return value if isinstance(value, BackendConfig) else None

    @property
    def functional_backends(self) -> set[str]:
        """Get the set of functional backends (those with API keys)."""
        functional: set[str] = set()
        registered = backend_registry.get_registered_backends()
        for backend_name in registered:
            if backend_name in self.__dict__:
                config: Any = self.__dict__[backend_name]
                if isinstance(config, BackendConfig) and config.api_key:
                    functional.add(backend_name)

        oauth_like: set[str] = set()
        for name in registered:
            if name.endswith("-oauth") or name.startswith("gemini-oauth"):
                oauth_like.add(name)
            if name == "gemini-cli-cloud-project":
                oauth_like.add(name)

        functional.update(oauth_like.intersection(set(registered)))

        for name, cfg in getattr(self, "__dict__", {}).items():
            if (
                name == "default_backend"
                or name.startswith("_")
                or not isinstance(cfg, BackendConfig)
            ):
                continue
            if cfg.api_key:
                functional.add(name)
        return functional

    def __getattr__(self, name: str) -> Any:
        """Allow accessing backend configs as attributes.

        If an attribute for a backend is missing, create a default
        BackendConfig instance lazily. This ensures tests and runtime
        code can access `config.backends.openai` / `config.backends.gemini`
        even if the registry hasn't been populated yet.
        """
        if name == "default_backend":
            if "default_backend" in self.__dict__:
                return self.__dict__["default_backend"]
            return "openai"

        if name in self.__dict__:
            return cast(BackendConfig, self.__dict__[name])

        if name.startswith(("_", "__")):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

        if not hasattr(self, "_initialization_complete"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

        config = BackendConfig()
        self.__dict__[name] = config
        return config

    @model_serializer(mode="wrap")
    def serialize_model(self, handler: Any) -> dict[str, Any]:
        """Custom serializer to include dynamic backends."""
        dumped: dict[str, Any] = handler(self)

        registered = backend_registry.get_registered_backends()
        for backend_name in registered:
            if backend_name in self.__dict__:
                config: Any = self.__dict__[backend_name]
                if isinstance(config, BackendConfig):
                    dumped[backend_name] = config.model_dump()

        for key, value in self.__dict__.items():
            if (
                key not in dumped
                and isinstance(value, BackendConfig)
                and key != "default_backend"
            ):
                dumped[key] = value.model_dump()

        return dumped

    def model_is_functional(self, model_id: str) -> bool:
        """Check if a model is available in any functional backend."""
        if ":" not in model_id:
            return False

        backend_name, _ = model_id.split(":", 1)
        return backend_name in self.functional_backends


def normalize_credentials_path(path: str) -> str:
    return str(Path(path).resolve())
