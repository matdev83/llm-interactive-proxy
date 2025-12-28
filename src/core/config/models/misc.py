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


class ResilienceConfig(DomainModel):
    """Resilience scoping configuration."""

    model_config = ConfigDict(frozen=True)

    personal_backend_types: list[str] | None = Field(default=None)
    """Backend types that should be scoped per user/session (personal by default)."""

    shared_backend_types: list[str] | None = Field(default=None)
    """Backend types that should always use shared resilience state."""
