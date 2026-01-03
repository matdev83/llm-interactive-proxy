"""Tool Access Policy Service for controlling tool access based on policies."""

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from src.core.common.logging_utils import get_logger
from src.core.config.app_config import ToolCallReactorConfig

logger = get_logger(__name__)


class ToolFilterMetadata(BaseModel):
    """Metadata for tool filtering operations."""

    policy_applied: str | None = None
    original_tool_count: int = 0
    filtered_tool_names: list[str] = Field(default_factory=list)
    filtered_tool_count: int = 0
    evaluation_time_ms: float = 0.0


class ToolFilterResult(BaseModel):
    """Result of filtering tool definitions."""

    filtered_tools: list[dict[str, Any]]
    metadata: ToolFilterMetadata


class ToolCheckMetadata(BaseModel):
    """Metadata for tool access check operations."""

    policy_applied: str | None = None
    tool_name: str = ""
    reason: str = ""
    evaluation_time_ms: float = 0.0


class ToolCheckResult(BaseModel):
    """Result of checking if a tool is allowed."""

    is_allowed: bool
    metadata: ToolCheckMetadata


@dataclass
class AccessPolicy:
    """Represents a single tool access policy."""

    name: str
    model_pattern: str
    agent_pattern: str | None = None
    allowed_patterns: list[str] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    default_policy: str = "allow"
    block_message: str = "This tool is not allowed by the current access policy."
    priority: int = 0

    # Compiled patterns (cached)
    _model_regex: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _agent_regex: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _allowed_regexes: list[re.Pattern[str]] = field(
        default_factory=list, init=False, repr=False
    )
    _blocked_regexes: list[re.Pattern[str]] = field(
        default_factory=list, init=False, repr=False
    )

    def compile_patterns(self) -> None:
        """Compile all regex patterns for efficient matching."""
        try:
            self._model_regex = re.compile(self.model_pattern, re.IGNORECASE)
        except re.error as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failed to compile model_pattern '{self.model_pattern}' "
                    f"in policy '{self.name}': {e}",
                    exc_info=True,
                )
            self._model_regex = None

        if self.agent_pattern:
            try:
                self._agent_regex = re.compile(self.agent_pattern, re.IGNORECASE)
            except re.error as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Failed to compile agent_pattern '{self.agent_pattern}' "
                        f"in policy '{self.name}': {e}",
                        exc_info=True,
                    )
                self._agent_regex = None

        self._allowed_regexes = []
        for pattern in self.allowed_patterns:
            try:
                self._allowed_regexes.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Failed to compile allowed pattern '{pattern}' "
                        f"in policy '{self.name}': {e}",
                        exc_info=True,
                    )

        self._blocked_regexes = []
        for pattern in self.blocked_patterns:
            try:
                self._blocked_regexes.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Failed to compile blocked pattern '{pattern}' "
                        f"in policy '{self.name}': {e}",
                        exc_info=True,
                    )

    def matches_context(self, model_name: str, agent: str | None = None) -> bool:
        """Check if this policy matches the given model and agent context."""
        if self._model_regex is None:
            return False

        if not self._model_regex.search(model_name):
            return False

        if self.agent_pattern:
            if agent is None:
                return False
            if self._agent_regex is None:
                return False
            if not self._agent_regex.search(agent):
                return False

        return True

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed by this policy.

        Precedence: allowed patterns override blocked patterns.
        """
        # Check if tool matches any allowed pattern
        for regex in self._allowed_regexes:
            if regex.search(tool_name):
                return True

        # Check if tool matches any blocked pattern
        for regex in self._blocked_regexes:
            if regex.search(tool_name):
                return False

        # Fall back to default policy
        return self.default_policy == "allow"


class ToolAccessPolicyService:
    """Service for evaluating tool access policies."""

    def __init__(
        self,
        config: ToolCallReactorConfig,
        global_overrides: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with configuration and optional global CLI overrides.

        Args:
            config: Tool call reactor configuration containing access policies
            global_overrides: Optional global policy overrides from CLI
        """
        self._policies: list[AccessPolicy] = []
        self._global_policy: AccessPolicy | None = None

        # Performance metrics
        self._evaluation_count = 0
        self._total_evaluation_time_ms = 0.0

        # Policy lookup cache: (model_name, agent) -> AccessPolicy | None
        self._policy_cache: OrderedDict[tuple[str, str | None], AccessPolicy | None] = (
            OrderedDict()
        )
        self._policy_cache_size = 128
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_lock = threading.Lock()

        # Load policies from configuration
        self._load_policies(config)

        # Apply global overrides if provided
        if global_overrides:
            self._apply_global_overrides(global_overrides)

        # Sort policies by priority (highest first)
        self._policies.sort(key=lambda p: p.priority, reverse=True)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Loaded %d tool access policies", len(self._policies))
        if self._policies and logger.isEnabledFor(logging.DEBUG):
            logger.debug("Policy names: %s", [p.name for p in self._policies])

    def _load_policies(self, config: ToolCallReactorConfig) -> None:
        """Load policies from configuration."""
        access_policies = getattr(config, "access_policies", None)
        if not access_policies:
            return

        for policy_data in access_policies:
            try:
                # Validate required fields
                if not isinstance(policy_data, dict):
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Invalid policy data (not a dict): %s", policy_data
                        )
                    continue

                name = policy_data.get("name")
                model_pattern = policy_data.get("model_pattern")
                default_policy = policy_data.get("default_policy")

                if not name:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning("Policy missing 'name' field: %s", policy_data)
                    continue
                if not model_pattern:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Policy '%s' missing 'model_pattern' field", name
                        )
                    continue
                if not default_policy:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Policy '%s' missing 'default_policy' field", name
                        )
                    continue
                if default_policy not in ("allow", "deny"):
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Policy '%s' has invalid default_policy: %s",
                            name,
                            default_policy,
                        )
                    continue

                policy = AccessPolicy(
                    name=name,
                    model_pattern=model_pattern,
                    agent_pattern=policy_data.get("agent_pattern"),
                    allowed_patterns=policy_data.get("allowed_patterns", []),
                    blocked_patterns=policy_data.get("blocked_patterns", []),
                    default_policy=default_policy,
                    block_message=policy_data.get(
                        "block_message",
                        "This tool is not allowed by the current access policy.",
                    ),
                    priority=policy_data.get("priority", 0),
                )

                policy.compile_patterns()
                self._policies.append(policy)

            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error("Failed to load policy: %s", e, exc_info=True)

    def _apply_global_overrides(self, overrides: dict[str, Any]) -> None:
        """Apply global policy overrides from CLI."""
        try:
            self._global_policy = AccessPolicy(
                name="global_override",
                model_pattern=".*",  # Match all models
                agent_pattern=None,
                allowed_patterns=overrides.get("allowed_patterns", []),
                blocked_patterns=overrides.get("blocked_patterns", []),
                default_policy=overrides.get("default_policy", "allow"),
                block_message=overrides.get(
                    "block_message",
                    "This tool is not allowed by global policy.",
                ),
                priority=1000,  # Highest priority
            )
            self._global_policy.compile_patterns()
            if logger.isEnabledFor(logging.INFO):
                logger.info("Applied global policy overrides")
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Failed to apply global overrides: %s", e, exc_info=True)

    def _select_policy(
        self, model_name: str, agent: str | None = None
    ) -> AccessPolicy | None:
        """Select the most specific matching policy for the given context.

        Returns the highest priority policy that matches, or None if no match.
        Uses caching for improved performance.
        """
        # Global policy always takes precedence (no caching needed)
        if self._global_policy:
            return self._global_policy

        # Check cache
        cache_key = (model_name, agent)
        with self._cache_lock:
            if cache_key in self._policy_cache:
                self._policy_cache.move_to_end(cache_key)
                self._cache_hits += 1
                return self._policy_cache[cache_key]
            self._cache_misses += 1

        # Cache miss - find matching policy outside the lock so evaluation
        # of regex patterns does not block other callers.
        selected_policy: AccessPolicy | None = None

        for policy in self._policies:
            if policy.matches_context(model_name, agent):
                selected_policy = policy
                break

        # Cache the result
        with self._cache_lock:
            self._policy_cache[cache_key] = selected_policy
            if len(self._policy_cache) > self._policy_cache_size:
                self._policy_cache.popitem(last=False)
        return selected_policy

    def filter_tool_definitions(
        self,
        tools: list[dict[str, Any]],
        model_name: str,
        agent: str | None = None,
    ) -> ToolFilterResult:
        """Filter tool definitions based on policies.

        Args:
            tools: List of tool definitions
            model_name: Model name to match against policies
            agent: Optional agent identifier

        Returns:
            ToolFilterResult containing filtered tools and metadata.
        """
        import time

        start_time = time.perf_counter()

        policy = self._select_policy(model_name, agent)

        metadata = ToolFilterMetadata(
            policy_applied=policy.name if policy else None,
            original_tool_count=len(tools),
        )

        if not policy:
            metadata.filtered_tool_count = len(tools)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            metadata.evaluation_time_ms = elapsed_ms
            self._record_evaluation_time(elapsed_ms)
            return ToolFilterResult(filtered_tools=tools, metadata=metadata)

        filtered_tools: list[dict[str, Any]] = []
        filtered_names: list[str] = []

        for tool in tools:
            tool_name = self._extract_tool_name(tool)
            if tool_name and policy.is_tool_allowed(tool_name):
                filtered_tools.append(tool)
            elif tool_name:
                filtered_names.append(tool_name)

        metadata.filtered_tool_count = len(filtered_tools)
        metadata.filtered_tool_names = filtered_names

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        metadata.evaluation_time_ms = elapsed_ms
        self._record_evaluation_time(elapsed_ms)

        if filtered_names:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Filtered %d tool definitions for model %s by policy '%s': %s",
                    len(filtered_names),
                    model_name,
                    policy.name,
                    filtered_names,
                )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Remaining tools: %s",
                    [self._extract_tool_name(t) for t in filtered_tools],
                )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Policy evaluation time: %.3fms", elapsed_ms)

        return ToolFilterResult(filtered_tools=filtered_tools, metadata=metadata)

    def is_tool_allowed(
        self,
        tool_name: str,
        model_name: str,
        agent: str | None = None,
    ) -> ToolCheckResult:
        """Check if a tool is allowed by policies.

        Args:
            tool_name: Name of the tool to check
            model_name: Model name to match against policies
            agent: Optional agent identifier

        Returns:
            ToolCheckResult containing is_allowed flag and metadata.
        """
        import time

        start_time = time.perf_counter()

        policy = self._select_policy(model_name, agent)

        metadata = ToolCheckMetadata(
            policy_applied=policy.name if policy else None,
            tool_name=tool_name,
        )

        if not policy:
            metadata.reason = "no_policy_matched"
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            metadata.evaluation_time_ms = elapsed_ms
            self._record_evaluation_time(elapsed_ms)
            return ToolCheckResult(is_allowed=True, metadata=metadata)

        is_allowed = policy.is_tool_allowed(tool_name)
        metadata.reason = "allowed" if is_allowed else "blocked"

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        metadata.evaluation_time_ms = elapsed_ms
        self._record_evaluation_time(elapsed_ms)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Policy evaluation for '%s': %s in %.3fms",
                tool_name,
                metadata.reason,
                elapsed_ms,
            )

        return ToolCheckResult(is_allowed=is_allowed, metadata=metadata)

    def get_block_message(
        self,
        tool_name: str,
        model_name: str,
        agent: str | None = None,
    ) -> str:
        """Get the block message for a disallowed tool.

        Args:
            tool_name: Name of the blocked tool
            model_name: Model name to match against policies
            agent: Optional agent identifier

        Returns:
            Block message from the matched policy, or a default message.
        """
        policy = self._select_policy(model_name, agent)

        if policy:
            return policy.block_message

        return "This tool is not allowed by the current access policy."

    def _record_evaluation_time(self, elapsed_ms: float) -> None:
        """Record policy evaluation time for performance metrics.

        Args:
            elapsed_ms: Evaluation time in milliseconds.
        """
        self._evaluation_count += 1
        self._total_evaluation_time_ms += elapsed_ms

    def get_performance_metrics(self) -> dict[str, Any]:
        """Get performance metrics for policy evaluation.

        Returns:
            Dictionary containing performance metrics including cache statistics.
        """
        avg_time_ms = (
            self._total_evaluation_time_ms / self._evaluation_count
            if self._evaluation_count > 0
            else 0.0
        )

        total_cache_lookups = self._cache_hits + self._cache_misses
        cache_hit_rate = (
            (self._cache_hits / total_cache_lookups * 100)
            if total_cache_lookups > 0
            else 0.0
        )
        with self._cache_lock:
            cache_size = len(self._policy_cache)

        return {
            "evaluation_count": self._evaluation_count,
            "total_evaluation_time_ms": self._total_evaluation_time_ms,
            "average_evaluation_time_ms": avg_time_ms,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate_percent": cache_hit_rate,
            "cache_size": cache_size,
        }

    @staticmethod
    def _extract_tool_name(tool: dict[str, Any]) -> str | None:
        """Extract tool name from tool definition.

        Supports both OpenAI and Anthropic tool formats.
        """
        # OpenAI format: {"type": "function", "function": {"name": "..."}}
        if "function" in tool and isinstance(tool["function"], dict):
            return tool["function"].get("name")

        # Anthropic format: {"name": "..."}
        if "name" in tool:
            name = tool["name"]
            return str(name) if isinstance(name, str) else None

        return None
