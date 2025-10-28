"""Capability resolution helpers for the OpenAI Codex (Codex) connector."""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodexClientCapabilities:
    """Capability profile describing how to translate a client request for Codex."""

    protocol: str = "openai-chat"
    tool_text_format: str = "none"
    fallback_tool_text_format: str = "summary"
    codex_passthrough: bool = False
    prompt_mode: str = "codex_default"
    tool_schema_mode: str = "codex_default"
    bypass_tool_call_reactor: bool = False
    include_environment_context: bool = True

    def merge(self, overrides: Mapping[str, Any] | None) -> CodexClientCapabilities:
        """Return a new capability profile with overrides applied."""
        if not overrides:
            return self

        base = asdict(self)
        for key, value in overrides.items():
            if key in base and value is not None:
                base[key] = value
        return CodexClientCapabilities(**base)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation of the capability profile."""
        return asdict(self)


class CodexCapabilityResolver:
    """Resolve Codex client capabilities from request metadata."""

    _SUPPORTED_KEYS = {
        "protocol",
        "tool_text_format",
        "fallback_tool_text_format",
        "codex_passthrough",
        "prompt_mode",
        "tool_schema_mode",
        "bypass_tool_call_reactor",
        "include_environment_context",
    }
    _NESTED_KEYS = (
        "client_capabilities",
        "codex_capabilities",
        "capabilities",
    )
    _CLINE_LIKE_AGENTS = {"cline", "kilocode", "roocode"}
    _KILOCODE_ALIASES = {"kilocode", "kilo-code", "kilo_code", "kilocode.ai"}

    def __init__(
        self,
        default_capabilities: CodexClientCapabilities | None = None,
        agent_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._default = default_capabilities or CodexClientCapabilities()
        self._default_dict = self._default.to_dict()
        normalized_overrides: dict[str, dict[str, Any]] = {}
        if agent_overrides:
            for raw_agent, override in agent_overrides.items():
                if not isinstance(raw_agent, str):
                    continue
                agent_key = raw_agent.strip().lower()
                if not agent_key:
                    continue
                mapping = self._to_mapping(override)
                if not mapping:
                    continue
                filtered: dict[str, Any] = {}
                for key in self._SUPPORTED_KEYS:
                    if key in mapping and mapping[key] is not None:
                        filtered[key] = mapping[key]
                if filtered:
                    normalized_overrides[agent_key] = filtered
        self._agent_overrides = normalized_overrides

    def resolve(
        self,
        request_data: Any,
        metadata: Mapping[str, Any] | None = None,
    ) -> CodexClientCapabilities:
        """Derive the capability profile for the given request."""
        result = self._default

        session_overrides = self._extract_capability_mapping(metadata)
        if session_overrides:
            result = result.merge(session_overrides)

        extra_body_overrides = self._extract_capability_mapping(
            self._extract_extra_body(request_data)
        )
        if extra_body_overrides:
            result = result.merge(extra_body_overrides)

        direct_overrides = self._extract_capability_mapping(
            getattr(request_data, "client_capabilities", None)
        )
        if direct_overrides:
            result = result.merge(direct_overrides)

        agent = self._extract_agent(metadata, request_data)
        if agent in self._CLINE_LIKE_AGENTS and result.tool_text_format in (
            None,
            "none",
        ):
            result = result.merge({"tool_text_format": "codex_xml"})

        # Enhanced KiloCode detection with alias normalization
        if self._is_kilocode_agent(agent) and result.tool_text_format in (
            None,
            "none",
        ):
            result = result.merge({"tool_text_format": "codex_xml"})
        if agent and agent in self._agent_overrides:
            override = self._agent_overrides[agent]
            current = result.to_dict()
            filtered_overrides: dict[str, Any] = {}
            for key, value in override.items():
                # Only apply when current value still matches resolver default
                if current.get(key) == self._default_dict.get(key):
                    filtered_overrides[key] = value
            if filtered_overrides:
                result = result.merge(filtered_overrides)

        logger.debug(
            "Resolved Codex capabilities: %s",
            result.to_dict(),
        )
        return result

    @staticmethod
    def _to_mapping(candidate: Any) -> MutableMapping[str, Any] | None:
        """Coerce an arbitrary object into a mapping, when possible."""
        if isinstance(candidate, MutableMapping):
            return candidate
        if isinstance(candidate, Mapping):
            return dict(candidate)
        if hasattr(candidate, "model_dump") and callable(candidate.model_dump):
            try:
                dumped = candidate.model_dump()
                if isinstance(dumped, MutableMapping):
                    return dumped
                if isinstance(dumped, Mapping):
                    return dict(dumped)
            except Exception:
                return None
        if hasattr(candidate, "__dict__"):
            return dict(candidate.__dict__)
        return None

    def _extract_capability_mapping(self, source: Any) -> dict[str, Any]:
        """Extract supported capability keys from a nested structure."""
        mapping = self._to_mapping(source)
        if not mapping:
            return {}

        for nested_key in self._NESTED_KEYS:
            if nested_key in mapping:
                nested_mapping = self._to_mapping(mapping[nested_key])
                if nested_mapping:
                    mapping = nested_mapping
                    break

        overrides: dict[str, Any] = {}
        for key in self._SUPPORTED_KEYS:
            if key in mapping:
                overrides[key] = mapping[key]
        return overrides

    @staticmethod
    def _extract_extra_body(request_data: Any) -> Mapping[str, Any] | None:
        extra_body = getattr(request_data, "extra_body", None)
        if isinstance(extra_body, Mapping):
            return extra_body
        return None

    def _extract_agent(
        self, metadata: Mapping[str, Any] | None, request_data: Any
    ) -> str | None:
        """Identify if the request is associated with a known agent."""
        agent: str | None = None
        if metadata and isinstance(metadata, Mapping):
            candidate = metadata.get("agent")
            if isinstance(candidate, str):
                agent = candidate.lower()
        if not agent:
            agent_attr = getattr(request_data, "agent", None)
            if isinstance(agent_attr, str):
                agent = agent_attr.lower()
        if not agent:
            extra_body = self._extract_extra_body(request_data)
            if extra_body:
                candidate = extra_body.get("agent")
                if isinstance(candidate, str):
                    agent = candidate.lower()
        if agent:
            agent = agent.lower()
            if "/" in agent:
                agent = agent.split("/", 1)[0]
        return agent

    def _is_kilocode_agent(self, agent: str | None) -> bool:
        """Check if the agent is a KiloCode variant."""
        if not agent:
            return False

        # Normalize agent name for KiloCode detection
        normalized = agent.lower().replace("-", "").replace("_", "").replace(".", "")

        # Check direct matches first
        if normalized in {"kilocode", "kiloc", "kilo"}:
            return True

        # Check if it starts with kilocode variants
        return bool(normalized.startswith("kilocode"))
