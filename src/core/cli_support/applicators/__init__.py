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
- AssessmentApplicator: LLM assessment configuration
- MemoryApplicator: ProxyMem configuration
- FailureHandlingApplicator: failure handling configuration
- EditPrecisionApplicator: edit precision tuning
- IdentityApplicator: client identity override
- RoutingApplicator: routing policies
- CompactionApplicator: context compaction

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.4: New configuration domains can be added without modifying existing applicators
"""
