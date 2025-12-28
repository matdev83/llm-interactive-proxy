"""
Configuration for context compaction feature.

This module defines the configuration structure for intelligent context
compaction of stale tool outputs before LLM backend dispatch.

Requirements covered:
- 3.1-3.5: Token budget governance and thresholds
- 3.3: Enable/disable compaction flag
- 3.4: Per-tool allow/deny policies
"""

from dataclasses import dataclass, field
from typing import Any

from src.core.domain.compaction import ToolCategory


@dataclass
class CompactionConfig:
    """Configuration for context compaction feature.

    Controls when and how stale tool outputs are compacted in message
    histories before dispatch to LLM backends.

    Attributes:
        enabled: Master switch for compaction (Req 3.3)
        token_threshold: Estimated token count to trigger compaction (Req 3.1)
        max_tokens: Hard limit - emit warning if cannot reduce below (Req 3.2)
        allowed_tool_categories: Tool categories eligible for compaction (Req 3.4)
        denied_tool_categories: Tool categories never compacted (Req 3.4)
        max_stubs_per_resource: Maximum stub messages to keep per resource
        preserve_last_n_results: Always keep this many recent results per resource
        stub_template: Template for generating stub messages
        redact_resource_identifiers: Redact file paths/commands in stubs (Req 4.5)
    """

    enabled: bool = False
    token_threshold: int = 100_000  # Start compacting above this estimate
    max_tokens: int = 150_000  # Warn if cannot reduce below this
    redact_resource_identifiers: bool = (
        False  # Default: debuggability over security (Req 4.5)
    )

    # Tool category policies - empty means all allowed
    allowed_tool_categories: list[str] = field(default_factory=list)
    denied_tool_categories: list[str] = field(default_factory=list)

    # Compaction behavior
    max_stubs_per_resource: int = 1
    preserve_last_n_results: int = 1

    # Stub message template
    stub_template: str = (
        "[COMPACTED] Previous output for {resource} ({size} bytes) was removed "
        "because a newer result for this resource exists later in the conversation."
    )

    def is_tool_category_allowed(self, category: ToolCategory) -> bool:
        """Check if a tool category is eligible for compaction.

        Implements allow/deny list logic (Req 3.4):
        1. If category is in denied list, return False
        2. If allowed list is empty, all non-denied categories allowed
        3. If allowed list is non-empty, category must be in it

        Args:
            category: The tool category to check

        Returns:
            True if the category can be compacted
        """
        category_value = category.value

        # Denied list takes precedence
        if category_value in self.denied_tool_categories:
            return False

        # If allowed list is empty, allow all non-denied
        if not self.allowed_tool_categories:
            return True

        # Otherwise, must be in allowed list
        return category_value in self.allowed_tool_categories

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompactionConfig":
        """Create configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            CompactionConfig instance
        """
        return cls(
            enabled=data.get("enabled", False),
            token_threshold=data.get("token_threshold", 100_000),
            max_tokens=data.get("max_tokens", 150_000),
            allowed_tool_categories=data.get("allowed_tool_categories", []),
            denied_tool_categories=data.get("denied_tool_categories", []),
            max_stubs_per_resource=data.get("max_stubs_per_resource", 1),
            preserve_last_n_results=data.get("preserve_last_n_results", 1),
            stub_template=data.get("stub_template", cls.stub_template),
            redact_resource_identifiers=data.get("redact_resource_identifiers", False),
        )

    @classmethod
    def disabled(cls) -> "CompactionConfig":
        """Create a disabled configuration.

        Returns:
            CompactionConfig with enabled=False
        """
        return cls(enabled=False)

    @classmethod
    def default(cls) -> "CompactionConfig":
        """Create default configuration optimized for common use cases.

        Default policy:
        - Compact file read operations (view_file, read_file)
        - Compact search results (grep_search, codebase_search)
        - Compact test execution logs
        - Preserve file write and command execution results

        Returns:
            CompactionConfig with sensible defaults
        """
        return cls(
            enabled=False,
            token_threshold=100_000,
            max_tokens=150_000,
            allowed_tool_categories=[
                ToolCategory.FILE_READ.value,
                ToolCategory.VIEW_FILE.value,
                ToolCategory.SEARCH.value,
                ToolCategory.LIST_DIRECTORY.value,
                ToolCategory.TEST_EXECUTION.value,
            ],
            denied_tool_categories=[
                ToolCategory.FILE_WRITE.value,
                ToolCategory.COMMAND_EXECUTION.value,
            ],
            max_stubs_per_resource=1,
            preserve_last_n_results=1,
        )


@dataclass
class CompactionPolicies:
    """Runtime policy state for a compaction operation.

    Encapsulates the evaluated policies for a specific compaction run,
    including resolved configurations and resource states.

    Attributes:
        config: The base compaction configuration
        tool_allowlist: Set of tool names explicitly allowed
        tool_denylist: Set of tool names explicitly denied
    """

    config: CompactionConfig
    tool_allowlist: frozenset[str] = field(default_factory=frozenset)
    tool_denylist: frozenset[str] = field(default_factory=frozenset)

    def should_compact_tool(self, tool_name: str, category: ToolCategory) -> bool:
        """Determine if a specific tool should be compacted.

        Evaluation order:
        1. Tool-specific denylist (highest precedence)
        2. Tool-specific allowlist
        3. Category-based policy from config

        Args:
            tool_name: The tool name
            category: The tool category

        Returns:
            True if the tool output should be compacted when stale
        """
        normalized_name = tool_name.lower()

        # Tool-specific denylist
        if normalized_name in self.tool_denylist:
            return False

        # Tool-specific allowlist
        if normalized_name in self.tool_allowlist:
            return True

        # Fall back to category policy
        return self.config.is_tool_category_allowed(category)

    @classmethod
    def from_config(
        cls,
        config: CompactionConfig,
        tool_allowlist: set[str] | None = None,
        tool_denylist: set[str] | None = None,
    ) -> "CompactionPolicies":
        """Create policies from configuration.

        Args:
            config: Base configuration
            tool_allowlist: Optional tool-specific allowlist
            tool_denylist: Optional tool-specific denylist

        Returns:
            CompactionPolicies instance
        """
        return cls(
            config=config,
            tool_allowlist=frozenset(t.lower() for t in (tool_allowlist or set())),
            tool_denylist=frozenset(t.lower() for t in (tool_denylist or set())),
        )


@dataclass
class TokenBudgetConfig:
    """Token budget configuration for compaction decisions.

    Defines the thresholds that trigger and govern the compaction
    process based on estimated token usage (Req 3.1, 3.2).

    Attributes:
        compaction_threshold: Token estimate that triggers compaction
        max_tokens: Hard ceiling - warn if exceeded after compaction
        current_estimate: Current estimated token count for the request
    """

    compaction_threshold: int
    max_tokens: int
    current_estimate: int = 0

    @property
    def needs_compaction(self) -> bool:
        """Check if compaction should be triggered (Req 3.5).

        Returns:
            True if current estimate exceeds threshold
        """
        return self.current_estimate > self.compaction_threshold

    @property
    def exceeds_max(self) -> bool:
        """Check if estimate exceeds hard limit (Req 3.2).

        Returns:
            True if current estimate exceeds max_tokens
        """
        return self.current_estimate > self.max_tokens

    @classmethod
    def from_config(
        cls,
        config: CompactionConfig,
        current_estimate: int = 0,
    ) -> "TokenBudgetConfig":
        """Create token budget from compaction config.

        Args:
            config: Compaction configuration
            current_estimate: Current token estimate

        Returns:
            TokenBudgetConfig instance
        """
        return cls(
            compaction_threshold=config.token_threshold,
            max_tokens=config.max_tokens,
            current_estimate=current_estimate,
        )
