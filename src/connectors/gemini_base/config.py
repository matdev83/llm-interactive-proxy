"""
Configuration classes for Gemini OAuth Base.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.core.config.app_config import AppConfig

# Graceful degradation configuration
DEFAULT_RETRY_DELAYS = [15, 30, 60]  # Wait 15s, then 30s, then 60s between retries
DEFAULT_MAX_TOTAL_ATTEMPTS = 9  # Maximum total attempts across all models
DEFAULT_COOLDOWN_DURATION = 600.0  # 10 minutes cooldown after exhaustion
DEFAULT_RECOVERY_PROBE_INTERVAL = 120.0  # Check recovery every 2 minutes

# Code Assist API configuration
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
DEFAULT_CODE_ASSIST_MODEL = "gemini-1.5-pro-002"
DEFAULT_READ_TIMEOUT = 300.0
DEFAULT_CONNECTION_TIMEOUT = 10.0

# Code Assist plan-specific prompt allowance (per request).
# The margin stops us before the backend enforces the hard cap.
DEFAULT_CODE_ASSIST_PROMPT_LIMIT = 65_536
CODE_ASSIST_PROMPT_LIMIT_MARGIN = 0.97

# Default available models for fallback
DEFAULT_AVAILABLE_MODELS = [
    # Current generation (2.5 series) - DEFAULT models
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    # Preview models
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-pro-preview-06-05",
    "gemini-2.5-flash-preview-05-20",
    # 2.0 series
    "gemini-2.0-flash",
    "gemini-2.0-flash-thinking-exp-1219",
    "gemini-2.0-flash-preview-image-generation",
    # 1.5 series
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    # Embedding model
    "gemini-embedding-001",
]


@dataclass
class GracefulDegradationConfig:
    """Configuration for graceful degradation behavior."""

    enabled: bool = True
    retry_delays: list[float] = field(
        default_factory=lambda: list(DEFAULT_RETRY_DELAYS)
    )
    max_total_attempts: int = DEFAULT_MAX_TOTAL_ATTEMPTS
    cooldown_duration: float = DEFAULT_COOLDOWN_DURATION
    enable_recovery_probing: bool = True
    recovery_probe_interval: float = DEFAULT_RECOVERY_PROBE_INTERVAL
    model_fallbacks: dict[str, str] = field(default_factory=dict)
    generic_fallback_model: str | None = None
    base_cooldown_seconds: float = 60.0
    cooldown_multiplier: float = 2.0
    max_cooldown_seconds: float = 3600.0

    @classmethod
    def from_config(cls, config: AppConfig) -> "GracefulDegradationConfig":
        """Create configuration from AppConfig."""

        # AppConfig exposes attributes rather than dict-like `.get()` in some contexts
        def _coerce_list(value: Any, default: Sequence[float]) -> list[float]:
            if isinstance(value, list | tuple):
                return [float(v) for v in value]
            if value is None:
                return list(default)
            try:
                return [float(v) for v in list(value)]
            except Exception:
                return list(default)

        return cls(
            enabled=bool(getattr(config, "graceful_degradation_enabled", True)),
            retry_delays=_coerce_list(
                getattr(
                    config,
                    "graceful_degradation_retry_delays",
                    DEFAULT_RETRY_DELAYS,
                ),
                DEFAULT_RETRY_DELAYS,
            ),
            max_total_attempts=int(
                getattr(
                    config,
                    "graceful_degradation_max_attempts",
                    DEFAULT_MAX_TOTAL_ATTEMPTS,
                )
            ),
            cooldown_duration=float(
                getattr(
                    config,
                    "graceful_degradation_cooldown",
                    DEFAULT_COOLDOWN_DURATION,
                )
            ),
            enable_recovery_probing=bool(
                getattr(
                    config,
                    "graceful_degradation_recovery_probing",
                    True,
                )
            ),
            recovery_probe_interval=float(
                getattr(
                    config,
                    "graceful_degradation_probe_interval",
                    DEFAULT_RECOVERY_PROBE_INTERVAL,
                )
            ),
        )


@dataclass
class GracefulDegradationMetrics:
    """Lightweight telemetry for graceful degradation behavior."""

    total_invocations: int = 0
    total_attempts: int = 0
    fallback_invocations: int = 0
    total_wait_time: float = 0.0
    last_duration: float = 0.0

    def record_attempt(self) -> None:
        self.total_attempts += 1

    def record_wait(self, wait_seconds: float) -> None:
        if wait_seconds > 0:
            self.total_wait_time += wait_seconds

    def record_fallback(self) -> None:
        self.fallback_invocations += 1

    def record_duration(self, duration_seconds: float) -> None:
        self.last_duration = max(0.0, duration_seconds)

    def as_dict(self) -> dict[str, float | int]:
        return {
            "total_invocations": self.total_invocations,
            "total_attempts": self.total_attempts,
            "fallback_invocations": self.fallback_invocations,
            "total_wait_time": self.total_wait_time,
            "last_duration": self.last_duration,
        }


@dataclass
class ModelRetryState:
    """State tracking for model retry attempts."""

    model_name: str = ""
    attempts: int = 0
    failure_count: int = 0
    last_failure_time: float = 0.0
    cooldown_until: float = 0.0
    last_probe_attempt: float = 0.0
    probe_success_count: int = 0
    retry_after_until: float = 0.0
