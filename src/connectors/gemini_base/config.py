"""
Configuration primitives for Gemini OAuth connectors.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)

# Code Assist API endpoint (matching the CLI's endpoint):
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
# Timeouts
DEFAULT_CONNECTION_TIMEOUT = 60.0
DEFAULT_READ_TIMEOUT = 120.0

# Graceful degradation configuration
DEFAULT_RETRY_DELAYS = [5, 10]  # Wait 5s, then 10s between retries
DEFAULT_MAX_TOTAL_ATTEMPTS = 6
DEFAULT_COOLDOWN_DURATION = 600.0  # 10 minutes cooldown after exhaustion
DEFAULT_RECOVERY_PROBE_INTERVAL = 120.0  # Check recovery every 2 minutes

# Prompt limit configuration
DEFAULT_CODE_ASSIST_PROMPT_LIMIT = 65_536
CODE_ASSIST_PROMPT_LIMIT_MARGIN = 0.97

# Default available models for fallback
DEFAULT_AVAILABLE_MODELS = [
    # Current generation (3.x series)
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    # 2.5 series
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    # Embedding model
    "gemini-embedding-001",
]

# Standard models for gemini-oauth-* backends (auto, free, plan)
# This is a curated list of actively supported models for OAuth authentication flows.
GEMINI_OAUTH_STANDARD_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
]


def get_shared_gemini_fallback_models() -> list[str]:
    """Return the shared Gemini fallback catalog used across connector families."""

    ordered: list[str] = []
    seen: set[str] = set()
    for model in [*DEFAULT_AVAILABLE_MODELS, *GEMINI_OAUTH_STANDARD_MODELS]:
        if model in seen:
            continue
        seen.add(model)
        ordered.append(model)
    return ordered


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

    @classmethod
    def from_config(cls, config: AppConfig) -> "GracefulDegradationConfig":
        """Create configuration from AppConfig."""

        def _coerce_list(value: Any, default: Sequence[float]) -> list[float]:
            if isinstance(value, list | tuple):
                return [float(v) for v in value]
            if value is None:
                return list(default)
            try:
                return [float(v) for v in list(value)]
            except (TypeError, ValueError) as err:
                logger.debug(
                    "Failed to coerce graceful_degradation_retry_delays to list of floats: %s",
                    err,
                    exc_info=True,
                )
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

    attempts: int = 0
    cooldown_until: float = 0.0
    last_probe_attempt: float = 0.0
    probe_success_count: int = 0


__all__ = [
    "CODE_ASSIST_ENDPOINT",
    "DEFAULT_CONNECTION_TIMEOUT",
    "DEFAULT_READ_TIMEOUT",
    "DEFAULT_RETRY_DELAYS",
    "DEFAULT_MAX_TOTAL_ATTEMPTS",
    "DEFAULT_COOLDOWN_DURATION",
    "DEFAULT_RECOVERY_PROBE_INTERVAL",
    "DEFAULT_CODE_ASSIST_PROMPT_LIMIT",
    "CODE_ASSIST_PROMPT_LIMIT_MARGIN",
    "DEFAULT_AVAILABLE_MODELS",
    "GEMINI_OAUTH_STANDARD_MODELS",
    "get_shared_gemini_fallback_models",
    "GracefulDegradationConfig",
    "GracefulDegradationMetrics",
    "ModelRetryState",
]
