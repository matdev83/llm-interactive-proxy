"""
Semantic validation for configuration files.

This module provides validation beyond basic JSON schema validation,
checking for logical consistency and common configuration mistakes.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.core.common.backend_discovery_state import (
    get_oauth_install_command,
    get_optional_oauth_package_name,
    is_extracted_backend_name,
    normalize_backend_name,
)
from src.core.common.exceptions import ConfigurationError
from src.core.common.session_continuity_warnings import topic_similarity_enabled_warning
from src.core.config.app_config import AppConfig
from src.core.config.constrained_backend_policy import (
    group_constrained_backend_instances,
    is_constrained_connector_family,
)
from src.core.config.models.backends import BackendConfig, BackendSettings
from src.core.domain.composite_routing import (
    CompositeFailoverGroupNode,
    CompositeLeafNode,
    CompositeRoutePlan,
    CompositeRoutingInput,
    CompositeSelectorValidationError,
    CompositeWeightedGroupNode,
    RoutingSurface,
)
from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_backend,
)
from src.core.services.backend_registry import backend_registry
from src.core.services.composite_selector_parser import CompositeSelectorParser

logger = logging.getLogger(__name__)


class ConfigurationValidator:
    """Validates configuration for semantic correctness."""

    def __init__(self, config_data: dict[str, Any], config_path: str | Path) -> None:
        self.config_data = config_data
        self.config_path = str(config_path)
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self) -> None:
        """Run all semantic validations."""
        self._validate_wire_capture_config()
        self._validate_logging_config()
        self._validate_backend_config()
        self._validate_end_of_session_config()
        self._validate_session_continuity_config()

        if self.errors:
            raise ConfigurationError(
                message="Configuration validation failed",
                details={
                    "path": self.config_path,
                    "errors": self.errors,
                    "warnings": self.warnings,
                    "recovery_instructions": self._get_recovery_instructions(),
                },
            )

        if self.warnings:
            for warning in self.warnings:
                logger.warning("Configuration warning: %s", warning)

    def _validate_wire_capture_config(self) -> None:
        """Validate wire capture configuration."""
        logging_config = self.config_data.get("logging", {})

        log_file = logging_config.get("log_file")
        capture_file = logging_config.get("capture_file")

        # Check for common mistake: using log_file for wire capture
        if log_file and "wire_capture" in str(log_file).lower():
            self.errors.append(
                f"logging.log_file is set to '{log_file}' which appears to be intended for wire capture. "
                f"Use 'logging.capture_file' instead for wire-level HTTP capture. "
                f"'log_file' is for general application logs."
            )

        # Check for conflicting file paths
        if log_file and capture_file and log_file == capture_file:
            self.errors.append(
                f"logging.log_file and logging.capture_file cannot point to the same file: '{log_file}'. "
                f"These serve different purposes and must use separate files."
            )

        # Validate capture file configuration consistency
        if capture_file:
            capture_options = [
                "capture_max_bytes",
                "capture_truncate_bytes",
                "capture_max_files",
                "capture_rotate_interval_seconds",
                "capture_total_max_bytes",
            ]

            # Check if capture options are set without capture_file
            for option in capture_options:
                if logging_config.get(option) is not None:
                    # This is actually OK - capture_file enables the options
                    break
        else:
            # Check if capture options are set without capture_file
            capture_options_set: list[str] = []
            for option in [
                "capture_max_bytes",
                "capture_truncate_bytes",
                "capture_max_files",
            ]:
                if logging_config.get(option) is not None:
                    capture_options_set.append(option)

            if capture_options_set:
                self.warnings.append(
                    f"Wire capture options {capture_options_set} are set but logging.capture_file is not configured. "
                    f"These options will have no effect without capture_file."
                )

    def _validate_logging_config(self) -> None:
        """Validate general logging configuration."""
        logging_config = self.config_data.get("logging", {})

        # Check log level
        level = logging_config.get("level")
        if level and level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            self.errors.append(
                f"logging.level '{level}' is invalid. "
                f"Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )

    def _validate_backend_config(self) -> None:
        """Validate backend configuration."""
        backends_config = self.config_data.get("backends", {})
        default_backend = backends_config.get("default_backend")

        if default_backend and default_backend not in backends_config:
            self.warnings.append(
                f"backends.default_backend is set to '{default_backend}' but no configuration "
                f"exists for this backend. Ensure the backend is properly configured."
            )

        instance_keys = [
            key for key in backends_config if isinstance(key, str) and "." in key
        ]
        family_keys = [
            key
            for key in backends_config
            if isinstance(key, str)
            and "." not in key
            and is_constrained_connector_family(key)
            and not self._is_default_backend_config_payload(backends_config.get(key))
        ]
        backend_instance_names = instance_keys + family_keys
        constrained_groups = group_constrained_backend_instances(backend_instance_names)
        for family, instances in constrained_groups.items():
            if len(instances) <= 1:
                continue
            formatted_instances = ", ".join(instances)
            self.errors.append(
                "Constrained connector family "
                f"'{family}' violates single-instance policy. "
                f"Configured instances: [{formatted_instances}]. "
                "Keep exactly one proxy instance for this family."
            )

    @staticmethod
    def _is_default_backend_config_payload(payload: Any) -> bool:
        if isinstance(payload, BackendConfig):
            return payload == BackendConfig()
        if not isinstance(payload, dict):
            return False
        try:
            return BackendConfig(**payload) == BackendConfig()
        except Exception:
            return False

    def _validate_session_continuity_config(self) -> None:
        session_cfg = self.config_data.get("session")
        if not isinstance(session_cfg, dict):
            return

        continuity_cfg = session_cfg.get("session_continuity")
        if not isinstance(continuity_cfg, dict):
            return

        if continuity_cfg.get("enable_topic_similarity_matching") is True:
            self.warnings.append(topic_similarity_enabled_warning())

    def _validate_end_of_session_config(self) -> None:
        """Validate end-of-session configuration."""
        eos_config = self.config_data.get("end_of_session", {})

        if not eos_config:
            # No end_of_session config provided - defaults will be used
            return

        enabled = eos_config.get("enabled", False)
        emit_events = eos_config.get("emit_events", True)

        # Validate detect-only mode (enabled=True, emit_events=False)
        if enabled and not emit_events:
            self.warnings.append(
                "end_of_session.enabled=True but end_of_session.emit_events=False. "
                "This enables detect-only mode: detection runs but no events are emitted."
            )

        # Field-level validation (emission_ttl_seconds >= 0, dispatch_timeout_seconds >= 0.0)
        # is handled by Pydantic Field constraints when the config is loaded.
        # This semantic validation focuses on business logic consistency.

    def _get_recovery_instructions(self) -> list[str]:
        """Generate actionable recovery instructions based on errors."""
        instructions: list[str] = []

        for error in self.errors:
            if "wire_capture" in error and "log_file" in error:
                instructions.append(
                    "Fix wire capture configuration:\n"
                    "  1. Change 'logging.log_file' to 'logging.capture_file'\n"
                    "  2. Set 'logging.log_file' to null or a different path for general logs\n"
                    "  3. Example:\n"
                    "     logging:\n"
                    "       log_file: null  # or 'logs/app.log'\n"
                    "       capture_file: 'logs/wire_capture.log'"
                )
            elif "same file" in error:
                instructions.append(
                    "Use separate files for different log types:\n"
                    "  - logging.log_file: for general application logs\n"
                    "  - logging.capture_file: for wire-level HTTP capture\n"
                    "  These must be different files or one should be null."
                )
            elif "level" in error and "invalid" in error:
                instructions.append(
                    "Fix log level:\n"
                    "  Set logging.level to one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"
                )
            elif (
                "Constrained connector family" in error
                and "single-instance policy" in error
            ):
                instructions.append(
                    "Consolidate constrained connector-family configuration:\n"
                    "  1. Keep exactly one configured proxy instance per constrained family\n"
                    "  2. Remove duplicate constrained instances from YAML and backend instance files\n"
                    "  3. If you need multiple credentials, keep one proxy instance and let the connector rotate identity internally"
                )

        if not instructions:
            instructions.append(
                "Check the configuration file syntax and ensure all required fields are present."
            )

        return instructions


def validate_config_semantics(
    config_data: dict[str, Any], config_path: str | Path
) -> None:
    """Validate configuration for semantic correctness.

    Args:
        config_data: The loaded configuration data
        config_path: Path to the configuration file (for error reporting)

    Raises:
        ConfigurationError: If validation fails
    """
    validator = ConfigurationValidator(config_data, config_path)
    validator.validate()


def validate_static_route(config: AppConfig) -> None:
    """Validate that static_route backend exists in registered backends.

    This function validates the runtime AppConfig object (post YAML/ENV/CLI merge)
    and assumes connector auto-discovery has already happened.

    Args:
        config: The final resolved AppConfig instance

    Raises:
        ConfigurationError: If static_route specifies an invalid backend name or
            has an invalid format

    Note:
        This validation runs against the runtime AppConfig object, not raw YAML dict data.
        Connector auto-discovery (importing src.connectors) must have occurred before
        calling this function.
    """
    static_route = config.backends.static_route

    # No-op if static_route is None or empty string
    if not static_route:
        return

    # Validate explicit backend:model selector semantics.
    if not has_explicit_backend_selector(static_route):
        error_msg = (
            f"Invalid static_route format: '{static_route}'. "
            f"Expected explicit backend:model format (<backend_name>:<model_name>).\n"
            f"Model-only selectors (for example 'vendor/model:free') are not valid for static_route.\n"
            f"Example: gemini:gemini-2.5-pro"
        )
        logger.error("Static route validation failed: %s", error_msg)
        raise ConfigurationError(
            message=error_msg,
            details={
                "error_code": "invalid_static_route_format",
                "static_route": static_route,
                "expected_format": "<backend_name>:<model_name>",
                "example": "gemini:gemini-2.5-pro",
            },
        )

    parsed = parse_model_backend(static_route, "")
    backend_name = parsed.backend_type.strip()
    model_name = parsed.model_name.strip()

    if not backend_name:
        error_msg = (
            f"Invalid static_route format: '{static_route}'. "
            f"Backend name cannot be empty.\n"
            f"Expected format: <backend_name>:<model_name>\n"
            f"Example: gemini:gemini-2.5-pro"
        )
        logger.error("Static route validation failed: %s", error_msg)
        raise ConfigurationError(
            message=error_msg,
            details={
                "error_code": "invalid_static_route_format",
                "static_route": static_route,
                "expected_format": "<backend_name>:<model_name>",
                "example": "gemini:gemini-2.5-pro",
            },
        )

    # Validate model part is not empty
    if not model_name:
        error_msg = (
            f"Invalid static_route format: '{static_route}'. "
            f"Model name cannot be empty.\n"
            f"Expected format: <backend_name>:<model_name>\n"
            f"Example: gemini:gemini-2.5-pro"
        )
        logger.error("Static route validation failed: %s", error_msg)
        raise ConfigurationError(
            message=error_msg,
            details={
                "error_code": "invalid_static_route_format",
                "static_route": static_route,
                "expected_format": "<backend_name>:<model_name>",
                "example": "gemini:gemini-2.5-pro",
            },
        )

    # Validate backend exists in registered backends
    registered_backends = backend_registry.get_registered_backends()

    if backend_name not in registered_backends:
        # Extracted backends are optional and may be absent by design.
        # Startup fail/warn policy for missing extracted references is handled in
        # validate_extracted_backend_references().
        if is_extracted_backend_name(backend_name):
            return

        available_backends = sorted(registered_backends)
        available_backends_str = ", ".join(available_backends)

        error_msg = (
            f"Invalid backend '{backend_name}' specified in static_route.\n"
            f"Backend '{backend_name}' is not registered.\n"
            f"Available backends: {available_backends_str}\n"
            f"Current static_route value: '{static_route}'\n"
            f"Expected format: <backend_name>:<model_name>\n"
            f"Example: gemini:gemini-2.5-pro"
        )
        logger.error("Static route validation failed: %s", error_msg)
        raise ConfigurationError(
            message=error_msg,
            details={
                "invalid_backend": backend_name,
                "available_backends": available_backends,
                "static_route": static_route,
                "expected_format": "<backend_name>:<model_name>",
                "example": "gemini:gemini-2.5-pro",
            },
        )


def _collect_runtime_referenced_backends(config: AppConfig) -> set[str]:
    backends = getattr(config, "backends", None)
    if backends is None:
        return set()

    references: set[str] = set()

    default_backend = getattr(backends, "default_backend", None)
    if isinstance(default_backend, str) and default_backend.strip():
        references.add(default_backend.strip())

    static_route = getattr(backends, "static_route", None)
    if (
        isinstance(static_route, str)
        and static_route.strip()
        and has_explicit_backend_selector(static_route)
    ):
        parsed = parse_model_backend(static_route, "")
        backend_name = parsed.backend_type.strip()
        if backend_name:
            references.add(backend_name)

    default_backend_config = BackendConfig()
    for raw_name, value in getattr(backends, "__dict__", {}).items():
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or raw_name.startswith("_")
            or raw_name in {"default_backend", "static_route"}
            or raw_name in BackendSettings.model_fields
        ):
            continue
        if "." in raw_name:
            references.add(raw_name)
            continue
        if isinstance(value, BackendConfig) and value != default_backend_config:
            references.add(raw_name)

    return references


def validate_extracted_backend_references(config: AppConfig) -> None:
    """Validate runtime references to optional extracted backends.

    Behavior:
    - If extracted backend references are missing but at least one configured
      reference is registered, startup continues with warning.
    - If extracted backend references are missing and no configured/registered
      path remains, raise ConfigurationError with install guidance.
    """
    referenced_backends = _collect_runtime_referenced_backends(config)
    if not referenced_backends:
        return

    normalized_registered_backends = {
        normalize_backend_name(name)
        for name in backend_registry.get_registered_backends()
    }
    normalized_referenced_backends = {
        normalize_backend_name(name) for name in referenced_backends
    }

    missing_extracted_backends = sorted(
        backend_name
        for backend_name in normalized_referenced_backends
        if is_extracted_backend_name(backend_name)
        and backend_name not in normalized_registered_backends
    )
    if not missing_extracted_backends:
        return

    viable_registered_references = sorted(
        backend_name
        for backend_name in normalized_referenced_backends
        if backend_name in normalized_registered_backends
    )

    install_command = get_oauth_install_command()
    optional_package = get_optional_oauth_package_name()
    missing_backends_text = ", ".join(missing_extracted_backends)

    if viable_registered_references:
        logger.warning(
            "Configured extracted backend(s) are unavailable: %s. "
            "Startup continues because registered alternatives are configured: %s. "
            "Install optional package '%s' with '%s'.",
            missing_backends_text,
            ", ".join(viable_registered_references),
            optional_package,
            install_command,
        )
        return

    raise ConfigurationError(
        message=(
            "Configured extracted backend(s) are unavailable and no viable configured "
            f"registered backend path remains: {missing_backends_text}. "
            f"Install optional package '{optional_package}' using '{install_command}', "
            "or switch default_backend/static_route to a registered core backend."
        ),
        details={
            "error_code": "missing_extracted_backends_no_viable_path",
            "missing_extracted_backends": missing_extracted_backends,
            "configured_backend_references": sorted(normalized_referenced_backends),
            "registered_backends": sorted(normalized_registered_backends),
            "install_command": install_command,
            "optional_package": optional_package,
        },
    )


def _collect_runtime_constrained_backend_names(config: AppConfig) -> list[str]:
    backends = getattr(config, "backends", None)
    if backends is None:
        return []

    configured_names: list[str] = []
    default_backend_config = BackendConfig()
    for raw_name, value in getattr(backends, "__dict__", {}).items():
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or raw_name == "default_backend"
            or raw_name.startswith("_")
        ):
            continue
        if "." in raw_name:
            configured_names.append(raw_name)
            continue
        if not is_constrained_connector_family(raw_name):
            continue
        if isinstance(value, BackendConfig) and value != default_backend_config:
            configured_names.append(raw_name)

    return sorted(set(configured_names))


def validate_constrained_backend_instances(config: AppConfig) -> None:
    """Validate constrained connector-family policy on merged runtime config."""
    constrained_backend_names = _collect_runtime_constrained_backend_names(config)
    constrained_groups = group_constrained_backend_instances(constrained_backend_names)
    conflicts = {
        family: instances
        for family, instances in constrained_groups.items()
        if len(instances) > 1
    }
    if not conflicts:
        return

    conflict_fragments = [
        f"{family}: [{', '.join(instances)}]"
        for family, instances in sorted(conflicts.items())
    ]
    raise ConfigurationError(
        message=(
            "Constrained connector-family single-instance policy violated in merged runtime configuration. "
            + "; ".join(conflict_fragments)
        ),
        details={
            "error_code": "constrained_family_single_instance_violation",
            "constrained_family_conflicts": conflicts,
            "configured_backend_instances": constrained_backend_names,
            "migration_guidance": [
                "Keep exactly one proxy instance per constrained connector family.",
                "Remove duplicate constrained-family instances from merged sources (YAML, environment, backend instance files).",
                "If multiple credentials are required, keep one proxy instance and delegate identity rotation to connector-internal scheduling.",
            ],
        },
    )


def _validate_alias_replacement_backends(
    plan: CompositeRoutePlan,
    registered_backends: set[str],
    replacement: str,
    alias_pattern: str,
    available_backends: list[str],
) -> None:
    def _collect_leaf_nodes(node):
        if isinstance(node, CompositeLeafNode):
            return [node]
        if isinstance(node, CompositeFailoverGroupNode | CompositeWeightedGroupNode):
            leaves: list[CompositeLeafNode] = []
            for child in node.children:
                leaves.extend(_collect_leaf_nodes(child))
            return leaves
        return []

    leaf_nodes = _collect_leaf_nodes(plan.root_node)

    for leaf_node in leaf_nodes:
        leaf = leaf_node.leaf_selector
        normalized = leaf.normalized_selector

        if not has_explicit_backend_selector(normalized):
            continue

        parsed = parse_model_backend(normalized, "")
        backend_name = parsed.backend_type.strip()

        if not backend_name:
            raise ConfigurationError(
                message=(
                    f"Model alias replacement has empty backend name in branch '{normalized}'. "
                    f"Alias pattern: '{alias_pattern}', replacement: '{replacement}'. "
                    f"Explicit backend selectors must specify a non-empty backend."
                ),
                details={
                    "error_code": "invalid_alias_backend",
                    "alias_pattern": alias_pattern,
                    "replacement": replacement,
                    "failing_branch": normalized,
                    "reason": "empty_backend_name",
                },
            )

        if not parsed.model_name.strip():
            raise ConfigurationError(
                message=(
                    f"Model alias replacement has empty model name in branch '{normalized}'. "
                    f"Alias pattern: '{alias_pattern}', replacement: '{replacement}'. "
                    f"Explicit backend selectors must specify a non-empty model."
                ),
                details={
                    "error_code": "invalid_alias_backend",
                    "alias_pattern": alias_pattern,
                    "replacement": replacement,
                    "failing_branch": normalized,
                    "reason": "empty_model_name",
                },
            )

        if backend_name not in registered_backends and not is_extracted_backend_name(
            backend_name
        ):
            raise ConfigurationError(
                message=(
                    f"Model alias replacement references unknown backend '{backend_name}' "
                    f"in branch '{normalized}'. "
                    f"Alias pattern: '{alias_pattern}', replacement: '{replacement}'. "
                    f"Available backends: {', '.join(available_backends)}"
                ),
                details={
                    "error_code": "unknown_alias_backend",
                    "alias_pattern": alias_pattern,
                    "replacement": replacement,
                    "failing_branch": normalized,
                    "invalid_backend": backend_name,
                    "available_backends": available_backends,
                },
            )


def _is_alias_selector(value: str | None) -> bool:
    """Check if a selector string uses alias: or auto: namespace."""
    if not value or ":" not in value:
        return False
    namespace, _, _ = value.partition(":")
    return namespace.strip().lower() in {"alias", "auto"}


def warn_if_alias_references_without_rules(config: AppConfig) -> None:
    """Warn at startup when config references alias:/auto: selectors but model_aliases is empty.

    This is a fail-open warning (no exception raised) intended to surface the
    common misconfiguration where the server starts without `--config` and
    therefore has no alias rules, while some settings still reference alias
    selectors.
    """
    alias_rules = getattr(config, "model_aliases", None)
    if isinstance(alias_rules, list) and alias_rules:
        return

    hints: list[str] = []

    session_cfg = getattr(config, "session", None)
    if session_cfg is not None:
        qv_model = getattr(session_cfg, "quality_verifier_model", None)
        if _is_alias_selector(qv_model):
            hints.append(f"session.quality_verifier_model='{qv_model}'")

    backends_cfg = getattr(config, "backends", None)
    if backends_cfg is not None:
        static_route = getattr(backends_cfg, "static_route", None)
        if _is_alias_selector(static_route):
            hints.append(f"backends.static_route='{static_route}'")

    aux_cfg = getattr(config, "auxiliary_routing", None)
    if aux_cfg is not None:
        aux_model = getattr(aux_cfg, "model", None)
        if _is_alias_selector(aux_model):
            hints.append(f"auxiliary_routing.model='{aux_model}'")

    replacement_rules = getattr(config, "replacement_rules", None)
    if isinstance(replacement_rules, list):
        for idx, rule in enumerate(replacement_rules):
            to_selector = getattr(rule, "to_backend_model", None) or getattr(
                rule, "replacement", None
            )
            if _is_alias_selector(to_selector):
                hints.append(f"replacement_rules[{idx}].to='{to_selector}'")

    if not hints:
        return

    logger.warning(
        "The following settings use alias:/auto: selectors, but model_aliases "
        "is empty. If you expected YAML aliases, restart with the intended "
        "--config file.  Affected settings: %s",
        "; ".join(hints),
    )


def validate_model_aliases(config: AppConfig) -> None:
    """Validate model alias patterns and replacement routing strings at startup.

    Runs after backend discovery so that explicit backend names in replacement
    strings can be verified against the registered backend registry.

    Validates:
    - Regex pattern syntax is valid.
    - Replacement string is valid composite routing grammar (|, ^, [weight=N]).
    - No raw separator characters in query-param values.
    - Explicit backend names reference registered backends.

    Raises:
        ConfigurationError: If any alias fails validation.
    """
    aliases = getattr(config, "model_aliases", [])
    if not aliases:
        return

    registered_backends = set(backend_registry.get_registered_backends())
    available_backends = sorted(registered_backends)
    parser = CompositeSelectorParser()

    for idx, alias in enumerate(aliases):
        pattern = getattr(alias, "pattern", None)
        replacement = getattr(alias, "replacement", None)

        if not pattern:
            raise ConfigurationError(
                message=(
                    f"Model alias at index {idx} has empty pattern. "
                    f"Each alias must define a non-empty regex pattern."
                ),
                details={
                    "error_code": "invalid_alias_pattern",
                    "alias_index": idx,
                    "reason": "empty_pattern",
                },
            )

        if not replacement:
            raise ConfigurationError(
                message=(
                    f"Model alias at index {idx} has empty replacement. "
                    f"Each alias must define a non-empty replacement string."
                ),
                details={
                    "error_code": "invalid_alias_replacement",
                    "alias_index": idx,
                    "alias_pattern": pattern,
                    "reason": "empty_replacement",
                },
            )

        try:
            re.compile(pattern)
        except re.error as e:
            raise ConfigurationError(
                message=(
                    f"Model alias at index {idx} has invalid regex pattern: '{pattern}'. "
                    f"Error: {e}"
                ),
                details={
                    "error_code": "invalid_alias_regex",
                    "alias_index": idx,
                    "alias_pattern": pattern,
                    "regex_error": str(e),
                },
            )

        routing_input = CompositeRoutingInput(
            selector=replacement,
            surface=RoutingSurface.MAIN,
            require_explicit_backend=False,
        )

        try:
            plan = parser.parse(routing_input)
        except CompositeSelectorValidationError as e:
            raise ConfigurationError(
                message=(
                    f"Model alias at index {idx} has invalid replacement syntax: '{replacement}'. "
                    f"Alias pattern: '{pattern}'. "
                    f"Error: {e.message}. "
                    f"Note: raw separator characters (^, |) in query values must be URL-encoded "
                    f"(use %5E for ^, %7C for |)."
                ),
                details={
                    "error_code": "invalid_alias_replacement_syntax",
                    "alias_index": idx,
                    "alias_pattern": pattern,
                    "replacement": replacement,
                    "parser_error": e.envelope.message,
                },
            )

        _validate_alias_replacement_backends(
            plan,
            registered_backends,
            replacement,
            pattern,
            available_backends,
        )
