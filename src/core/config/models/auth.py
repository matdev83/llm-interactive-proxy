from __future__ import annotations

from pydantic import ConfigDict, Field

from src.core.interfaces.model_bases import DomainModel


class AuthConfig(DomainModel):
    """Authentication configuration."""

    model_config = ConfigDict(frozen=True)

    disable_auth: bool = False
    api_keys: list[str] = Field(default_factory=list)
    auth_token: str | None = None
    redact_api_keys_in_prompts: bool = True
    trusted_ips: list[str] = Field(default_factory=list)
    brute_force_protection: BruteForceProtectionConfig = Field(
        default_factory=lambda: BruteForceProtectionConfig()
    )


class BruteForceProtectionConfig(DomainModel):
    """Configuration for brute-force protection on API authentication."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    max_failed_attempts: int = 5
    ttl_seconds: int = 900
    initial_block_seconds: int = 30
    block_multiplier: float = 2.0
    max_block_seconds: int = 3600
