from __future__ import annotations

import logging
from typing import Any

from pydantic import ConfigDict, Field

from src.core.auth.sso.config import SSOConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.backends import BackendSettings
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.config.models.logging import LoggingConfig
from src.core.config.models.misc import (
    CodebuffConfig,
    EmptyResponseConfig,
    ResilienceConfig,
    UsageTrackingConfig,
)
from src.core.config.models.non_forwardable_config import NonForwardableTaggingConfig
from src.core.config.models.rewriting import (
    EditPrecisionConfig,
    ModelAliasRule,
    RewritingConfig,
)
from src.core.config.models.routing import RoutingConfig
from src.core.config.models.session import SessionConfig
from src.core.database.config import DatabaseConfig
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.failure_handling_config import FailureHandlingConfig
from src.core.domain.configuration.health_check_config import HealthCheckConfig
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
)
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
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
    gcp_project_id: str | None = None
    gemini_credentials_path: str | None = None
    disable_health_checks: bool = False
    enable_activity_tracking: bool = False

    request_dedup_window: float = 3.0
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
    assessment: AssessmentConfig = Field(default_factory=AssessmentConfig)

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
    failure_handling: FailureHandlingConfig = Field(
        default_factory=FailureHandlingConfig
    )
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    memory: MemoryConfiguration = Field(default_factory=MemoryConfiguration)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    non_forwardable_tagging: NonForwardableTaggingConfig = Field(
        default_factory=NonForwardableTaggingConfig
    )

    vtc_client_patterns: list[str] = Field(
        default_factory=lambda: ["cline", "kilo", "roo"]
    )

    app: Any = None

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
        """Set a configuration value (legacy convenience)."""
        setattr(self, key, value)
