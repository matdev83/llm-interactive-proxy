"""
Parameter Resolution Service

This module provides parameter resolution from multiple sources with precedence handling.
Tracks parameter sources for debugging and applies precedence rules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic.types import JsonValue

logger = logging.getLogger(__name__)


@dataclass
class ParameterSource:
    """Tracks the source and value of a parameter."""

    value: Any
    source: str  # "uri", "session", "header", "config", "default"

    def __repr__(self) -> str:
        return f"ParameterSource(value={self.value!r}, source={self.source!r})"


@dataclass
class ResolvedParameters:
    """Container for resolved parameters with source tracking."""

    temperature: ParameterSource | None = None
    reasoning_effort: ParameterSource | None = None
    top_p: ParameterSource | None = None
    top_k: ParameterSource | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        Extract just the parameter values for backend application.

        Returns:
            Dictionary with parameter names and their effective values,
            excluding None values.

        Examples:
            >>> params = ResolvedParameters(
            ...     temperature=ParameterSource(0.5, "uri"),
            ...     reasoning_effort=ParameterSource("high", "session")
            ... )
            >>> params.to_dict()
            {"temperature": 0.5, "reasoning_effort": "high"}
        """
        result: dict[str, Any] = {}

        if self.temperature is not None:
            result["temperature"] = self.temperature.value

        if self.top_p is not None:
            result["top_p"] = self.top_p.value

        if self.top_k is not None:
            result["top_k"] = self.top_k.value

        if self.reasoning_effort is not None:
            result["reasoning_effort"] = self.reasoning_effort.value

        return result

    def get_debug_info(self) -> dict[str, dict[str, Any]]:
        """
        Get parameter sources and values for debugging.

        Returns:
            Dictionary with parameter names mapped to their debug information
            including effective value and source.

        Examples:
            >>> params = ResolvedParameters(
            ...     temperature=ParameterSource(0.5, "uri")
            ... )
            >>> params.get_debug_info()
            {
                "temperature": {
                    "effective_value": 0.5,
                    "source": "uri"
                }
            }
        """
        result: dict[str, dict[str, Any]] = {}

        if self.temperature is not None:
            result["temperature"] = {
                "effective_value": self.temperature.value,
                "source": self.temperature.source,
            }

        if self.top_p is not None:
            result["top_p"] = {
                "effective_value": self.top_p.value,
                "source": self.top_p.source,
            }

        if self.top_k is not None:
            result["top_k"] = {
                "effective_value": self.top_k.value,
                "source": self.top_k.source,
            }

        if self.reasoning_effort is not None:
            result["reasoning_effort"] = {
                "effective_value": self.reasoning_effort.value,
                "source": self.reasoning_effort.source,
            }

        return result


class ParameterResolutionService:
    """
    Resolves model parameters from multiple sources with precedence.

    Precedence (highest to lowest):
    1. Interactive session commands
    2. URI parameters from the model string
    3. Request headers
    4. Configuration file defaults (lowest priority)

    The service tracks the source of each parameter value for debugging
    and transparency.
    """

    # Supported parameter names
    SUPPORTED_PARAMETERS = [
        "temperature",
        "top_p",
        "top_k",
        "reasoning_effort",
    ]

    def resolve_parameters(
        self,
        uri_params: dict[str, JsonValue] | None = None,
        header_params: dict[str, Any] | None = None,
        config_params: dict[str, Any] | None = None,
        session_params: dict[str, Any] | None = None,
        backend: str = "",
    ) -> ResolvedParameters:
        """
        Resolve parameters from all sources with precedence.

        Args:
            uri_params: Parameters from URI query string
            header_params: Parameters from request headers
            config_params: Parameters from configuration file
            session_params: Parameters from interactive session commands
            backend: Backend name for logging context

        Returns:
            ResolvedParameters with effective values and source tracking

        Examples:
            >>> service = ParameterResolutionService()
            >>> result = service.resolve_parameters(
            ...     uri_params={"temperature": 0.5},
            ...     config_params={"temperature": 0.8}
            ... )
            >>> result.temperature.value
            0.5
            >>> result.temperature.source
            'uri'
        """
        # Initialize with None values
        uri_params = uri_params or {}
        header_params = header_params or {}
        config_params = config_params or {}
        session_params = session_params or {}

        # Track overridden sources for debugging
        overridden_sources: dict[str, list[tuple[str, Any]]] = {
            param: [] for param in self.SUPPORTED_PARAMETERS
        }

        # Resolve each parameter with precedence
        resolved = ResolvedParameters()

        for param_name in self.SUPPORTED_PARAMETERS:
            resolved_value = self._resolve_single_parameter(
                param_name,
                uri_params,
                header_params,
                config_params,
                session_params,
                overridden_sources,
            )
            setattr(resolved, param_name, resolved_value)

        # Emit debug logs
        self._log_resolution_debug(backend, resolved, overridden_sources)

        return resolved

    def _resolve_single_parameter(
        self,
        param_name: str,
        uri_params: dict[str, JsonValue],
        header_params: dict[str, Any],
        config_params: dict[str, Any],
        session_params: dict[str, Any],
        overridden_sources: dict[str, list[tuple[str, Any]]],
    ) -> ParameterSource | None:
        """
        Resolve a single parameter from all sources with precedence.

        Precedence order (highest to lowest):
        1. session_params
        2. uri_params
        3. header_params
        4. config_params

        Args:
            param_name: Name of the parameter to resolve
            uri_params: URI parameters
            header_params: Header parameters
            config_params: Config parameters
            session_params: Session parameters
            overridden_sources: Dict to track overridden sources for debugging

        Returns:
            ParameterSource with the effective value and source, or None if not found
        """
        # Collect all sources in precedence order (lowest to highest)
        sources = [
            ("config", config_params.get(param_name)),
            ("header", header_params.get(param_name)),
            ("uri", uri_params.get(param_name)),
            ("session", session_params.get(param_name)),
        ]

        # Find the highest priority source with a value
        effective_source: ParameterSource | None = None

        for source_name, value in sources:
            if value is not None:
                # Track overridden sources
                if effective_source is not None:
                    overridden_sources[param_name].append(
                        (effective_source.source, effective_source.value)
                    )

                # Update effective source (higher priority)
                effective_source = ParameterSource(value=value, source=source_name)

        return effective_source

    def _log_resolution_debug(
        self,
        backend: str,
        resolved: ResolvedParameters,
        overridden_sources: dict[str, list[tuple[str, Any]]],
    ) -> None:
        """
        Emit debug logs showing parameter resolution details.

        Args:
            backend: Backend name for context
            resolved: Resolved parameters
            overridden_sources: Dict of overridden sources for each parameter
        """
        # Only log if there are resolved parameters
        debug_info = resolved.get_debug_info()
        if not debug_info:
            return

        # Build log message
        log_lines = [f"Parameter resolution for {backend}:"]

        for param_name, info in debug_info.items():
            effective_value = info["effective_value"]
            source = info["source"]

            # Build override information
            overrides = overridden_sources.get(param_name, [])
            if overrides:
                override_str = ", ".join([f"{src}={val}" for src, val in overrides])
                log_lines.append(
                    f"  {param_name}: {effective_value} (source: {source}, overrode: {override_str})"
                )
            else:
                log_lines.append(
                    f"  {param_name}: {effective_value} (source: {source})"
                )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("\n".join(log_lines))
