"""Domain Applicators Package.

This package contains domain-specific applicators that decompose the CLI configuration
application logic into focused, single-responsibility classes.

Each applicator:
- Implements the `DomainApplicator` protocol
- Handles only its specific configuration domain
- Is testable in isolation with mock AppConfig
- Follows the Open/Closed Principle for extensibility

Domain Applicators:
- ServerApplicator: host, port, timeout, command_prefix, context_window
- LoggingApplicator: log_file, log_level, capture settings, CBOR capture
- BackendApplicator: default_backend, API keys, static_route, hybrid settings
- SessionApplicator: session flags, planning phase, tool access, pytest settings
- AuthApplicator: auth flags, SSO settings, brute force protection
- MemoryApplicator: ProxyMem configuration
- FailureHandlingApplicator: failure handling configuration
- ResilienceApplicator: resilience scoping overrides
- EditPrecisionApplicator: edit precision tuning
- IdentityApplicator: client identity override
- RoutingApplicator: routing policies
- AuxiliaryRoutingApplicator: auxiliary request routing (title/summary generation)
- CompactionApplicator: context compaction
- DynamicCompressionApplicator: dynamic tool-output compression
- SandboxingApplicator: file access sandboxing
- EndOfSessionApplicator: end-of-session detection and event emission

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.4: New configuration domains can be added without modifying existing applicators
"""

from src.core.cli_support.applicators.access_mode_applicator import (
    AccessModeApplicator,
)
from src.core.cli_support.applicators.auth_applicator import AuthApplicator
from src.core.cli_support.applicators.auxiliary_routing_applicator import (
    AuxiliaryRoutingApplicator,
)
from src.core.cli_support.applicators.backend_applicator import BackendApplicator
from src.core.cli_support.applicators.compaction_applicator import CompactionApplicator
from src.core.cli_support.applicators.dynamic_compression_applicator import (
    DynamicCompressionApplicator,
)
from src.core.cli_support.applicators.editprecision_applicator import (
    EditPrecisionApplicator,
)
from src.core.cli_support.applicators.endofsession_applicator import (
    EndOfSessionApplicator,
)
from src.core.cli_support.applicators.failurehandling_applicator import (
    FailureHandlingApplicator,
)
from src.core.cli_support.applicators.identity_applicator import IdentityApplicator
from src.core.cli_support.applicators.logging_applicator import LoggingApplicator
from src.core.cli_support.applicators.memory_applicator import MemoryApplicator
from src.core.cli_support.applicators.model_registry_applicator import (
    ModelRegistryApplicator,
)
from src.core.cli_support.applicators.notification_applicator import (
    NotificationApplicator,
)
from src.core.cli_support.applicators.replacement_applicator import (
    ReplacementApplicator,
)
from src.core.cli_support.applicators.resilience_applicator import ResilienceApplicator
from src.core.cli_support.applicators.routing_applicator import RoutingApplicator
from src.core.cli_support.applicators.sandboxing_applicator import SandboxingApplicator
from src.core.cli_support.applicators.server_applicator import ServerApplicator
from src.core.cli_support.applicators.session_applicator import SessionApplicator

__all__ = [
    "AccessModeApplicator",
    "AuthApplicator",
    "AuxiliaryRoutingApplicator",
    "BackendApplicator",
    "CompactionApplicator",
    "DynamicCompressionApplicator",
    "EditPrecisionApplicator",
    "EndOfSessionApplicator",
    "FailureHandlingApplicator",
    "IdentityApplicator",
    "LoggingApplicator",
    "MemoryApplicator",
    "ModelRegistryApplicator",
    "NotificationApplicator",
    "ResilienceApplicator",
    "RoutingApplicator",
    "ReplacementApplicator",
    "SandboxingApplicator",
    "ServerApplicator",
    "SessionApplicator",
]
