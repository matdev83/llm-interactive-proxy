from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from src.core.auth.sso.config import SSOConfig
from src.core.config.models.access_mode import AccessModeConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.auxiliary_routing import AuxiliaryRoutingConfig
from src.core.config.models.backends import BackendSettings
from src.core.config.models.canonical_request_processing import (
    CanonicalRequestProcessingConfig,
)
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.config.models.logging import LoggingConfig
from src.core.config.models.misc import (
    CodebuffConfig,
    EmptyResponseConfig,
    ModelLimitEnforcementConfig,
    ModelRegistryConfig,
    ReasoningModelTokenFloorConfig,
    ResilienceConfig,
    UsageTrackingConfig,
)
from src.core.config.models.non_forwardable_config import NonForwardableTaggingConfig
from src.core.config.models.notification import NotificationConfig
from src.core.config.models.rewriting import (
    EditPrecisionConfig,
    ModelAliasRule,
    RewritingConfig,
)
from src.core.config.models.routing import RoutingConfig
from src.core.config.models.session import SessionConfig
from src.core.database.config import DatabaseConfig
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.dynamic_compression_config import (
    DynamicCompressionConfig,
)
from src.core.domain.configuration.failure_handling_config import FailureHandlingConfig
from src.core.domain.configuration.health_check_config import HealthCheckConfig
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
)
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.domain.configuration.usage_window_warmup_config import (
    UsageWindowWarmupConfig,
)
from src.core.domain.model_utils import ModelDefaults
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.model_bases import DomainModel
from src.core.memory.config import MemoryConfiguration


class AppConfigModel(DomainModel, IConfig):
    """Complete application configuration (pure domain model)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str | None = None
    anthropic_port: int | None = None
    proxy_timeout: int = 120
    command_prefix: str = "!/"
    strict_command_detection: bool = False
    context_window_override: int | None = None
    streaming_yield_interval: int = (
        100  # Number of chunks to batch before yielding to event loop
    )
    gcp_project_id: str | None = None
    gemini_credentials_path: str | None = None
    gemini_read_timeout: float = 120.0  # Default 2 minutes
    disable_health_checks: bool = False
    #: When True, do not start post-turn idle timers that terminate ACP agent subprocesses.
    disable_stale_acp_agent_kills: bool = False
    enable_activity_tracking: bool = False
    auto_append_first_prompt_filename: str | None = None
    auto_append_first_prompt_text: str | None = Field(default=None, exclude=True)

    request_dedup_window: float = 6.0
    request_dedup_max_cache: int = 10000

    default_rate_limit: int = 60
    default_rate_window: int = 60

    backends: BackendSettings = Field(default_factory=BackendSettings)
    model_defaults: dict[str, ModelDefaults] = Field(default_factory=dict)
    failover_routes: dict[str, dict[str, Any]] = Field(default_factory=dict)

    identity: AppIdentityConfig = Field(default_factory=AppIdentityConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    sso: SSOConfig | None = None
    session: SessionConfig = Field(default_factory=SessionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    empty_response: EmptyResponseConfig = Field(default_factory=EmptyResponseConfig)
    edit_precision: EditPrecisionConfig = Field(default_factory=EditPrecisionConfig)
    rewriting: RewritingConfig = Field(default_factory=RewritingConfig)
    reasoning_aliases: ReasoningAliasesConfig = Field(
        default_factory=lambda: ReasoningAliasesConfig(reasoning_alias_settings=[])
    )
    model_aliases: list[ModelAliasRule] = Field(default_factory=list)

    sandboxing: SandboxingConfiguration = Field(default_factory=SandboxingConfiguration)
    codebuff: CodebuffConfig = Field(default_factory=CodebuffConfig)
    usage_tracking: UsageTrackingConfig = Field(default_factory=UsageTrackingConfig)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    end_of_session: EndOfSessionConfig = Field(default_factory=EndOfSessionConfig)
    replacement: ReplacementConfig = Field(default_factory=ReplacementConfig)
    health_check: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    usage_window_warmup: UsageWindowWarmupConfig = Field(
        default_factory=UsageWindowWarmupConfig
    )
    failure_handling: FailureHandlingConfig = Field(
        default_factory=FailureHandlingConfig
    )
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    auxiliary_routing: AuxiliaryRoutingConfig = Field(
        default_factory=AuxiliaryRoutingConfig
    )
    canonical_request_processing: CanonicalRequestProcessingConfig = Field(
        default_factory=CanonicalRequestProcessingConfig
    )
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    dynamic_compression: DynamicCompressionConfig = Field(
        default_factory=DynamicCompressionConfig
    )
    memory: MemoryConfiguration = Field(default_factory=MemoryConfiguration)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    non_forwardable_tagging: NonForwardableTaggingConfig = Field(
        default_factory=NonForwardableTaggingConfig
    )

    model_registry: ModelRegistryConfig = Field(default_factory=ModelRegistryConfig)
    model_limit_enforcement: ModelLimitEnforcementConfig = Field(
        default_factory=ModelLimitEnforcementConfig
    )
    reasoning_model_token_floor: ReasoningModelTokenFloorConfig = Field(
        default_factory=ReasoningModelTokenFloorConfig
    )

    notifications: NotificationConfig = Field(default_factory=NotificationConfig)

    access_mode: AccessModeConfig = Field(default_factory=AccessModeConfig)

    vtc_client_patterns: list[str] = Field(
        default_factory=lambda: ["cline", "kilo", "roo"]
    )

    app: Any = None

    @field_validator("auto_append_first_prompt_filename", mode="before")
    @classmethod
    def validate_auto_append_first_prompt_filename(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("auto_append_first_prompt_filename must be a string")
        stripped = v.strip()
        if not stripped:
            return None
        suf = Path(stripped).suffix.lower()
        if suf not in (".txt", ".md"):
            raise ValueError(
                f"Invalid auto_append_first_prompt_filename {v!r}: "
                "must end with .txt or .md"
            )
        return stripped

    def model_is_functional(self, model_id: str) -> bool:
        return self.backends.model_is_functional(model_id)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dotted key path."""
        logger = logging.getLogger(__name__)
        keys = key.split(".")
        value: Any = self
        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k, default)
                else:
                    value = getattr(value, k, default)
            return value
        except (AttributeError, KeyError, TypeError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get configuration value for key '%s': %s",
                    key,
                    e,
                    exc_info=True,
                )
            return default

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value (legacy convenience).

        .. deprecated::
            ``IConfig.set()`` is deprecated.  Use ``model_copy(update=...)`` on
            the immutable model or mutate runtime state via ``ApplicationState``
            instead.
        """
        warnings.warn(
            "IConfig.set() is deprecated; use model_copy(update=...) or mutate "
            "runtime state via ApplicationState instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        setattr(self, key, value)
