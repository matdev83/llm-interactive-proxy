from __future__ import annotations

from pydantic import ConfigDict, Field

from src.core.interfaces.model_bases import DomainModel


class EmptyResponseConfig(DomainModel):
    """Configuration for empty response handling."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether the empty response recovery is enabled."""

    max_retries: int = 1
    """Maximum number of retries for empty responses."""


class CodebuffConfig(DomainModel):
    """Codebuff WebSocket server configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    websocket_path: str = "/ws"
    heartbeat_timeout_seconds: int = 60
    session_cleanup_hours: int = 1
    max_connections: int = 1000
    max_message_size_bytes: int = 1048576  # 1MB


class UsageTrackingConfig(DomainModel):
    """Usage tracking and statistics configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether detailed usage tracking is enabled."""

    persistence_path: str = "./var/usage_data.json"
    """Path for persistence file."""

    flush_interval_seconds: float = 30.0
    """Interval for periodic persistence (in seconds)."""

    max_records_in_memory: int = 100000
    """Maximum records to keep in memory before applying retention policies."""


class CircuitBreakerConfig(DomainModel):
    """Configuration for backend circuit breaker protection."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    failure_threshold: int = Field(default=3, ge=1, le=100)
    open_cooldown_seconds: float = Field(default=30.0, gt=0, le=3600)
    half_open_success_threshold: int = Field(default=1, ge=1, le=10)
    half_open_max_inflight: int = Field(default=1, ge=1, le=10)


class ResilienceConfig(DomainModel):
    """Resilience scoping configuration."""

    model_config = ConfigDict(frozen=True)

    personal_backend_types: list[str] | None = Field(default=None)
    """Backend types that should be scoped per user/session (personal by default)."""

    shared_backend_types: list[str] | None = Field(default=None)
    """Backend types that should always use shared resilience state."""

    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    """Circuit breaker thresholds and behavior."""


class ModelRegistryConfig(DomainModel):
    """Configuration for the external model registry."""

    model_config = ConfigDict(frozen=True)

    download_enabled: bool = True
    """Whether to download updates from the external registry."""

    url: str = "https://models.dev/api.json"
    """URL of the model registry."""

    update_interval_seconds: int = 86400  # 1 day
    """Interval for checking for updates."""

    cache_path: str = "./var/model_registry/models.dev.json"
    """Path to the cached model registry file."""

    bootstrap_path: str = "./src/resources/model_registry/models.dev.json"
    """Path to the bootstrap model registry file."""


class ModelLimitEnforcementConfig(DomainModel):
    """Configuration for model limit enforcement."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether to enforce model limits (context window, etc.)."""


def _default_reasoning_model_token_floors() -> dict[str, int]:
    """Default min output tokens for reasoning-first models to prevent empty assistant messages."""
    return {
        "stepfun/step-3.5-flash:free": 512,
        "kimi/kimi-for-coding": 512,
        "kimi-for-coding": 512,
    }


class ReasoningModelTokenFloorConfig(DomainModel):
    """Configuration for reasoning-model token floor (prevents empty assistant messages)."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether to enforce minimum output tokens for reasoning-first models."""

    models: dict[str, int] = Field(
        default_factory=_default_reasoning_model_token_floors
    )
    """Model ID (normalized) -> minimum output tokens. Override or extend built-in defaults."""
