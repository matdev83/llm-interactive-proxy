"""Domain configuration for dynamic tool-output compression."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from src.core.domain.base import ValueObject


class CompressionLevel(str, Enum):
    """Compression aggressiveness level."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class MarkerStyle(str, Enum):
    """Inline marker placement for plain-text payloads."""

    PREFIX = "prefix"
    SUFFIX = "suffix"
    NONE = "none"


class CompressionMarkerConfig(ValueObject):
    """Marker policy for compressed outputs."""

    enabled: bool = True
    style: MarkerStyle = MarkerStyle.PREFIX
    include_sizes: bool = True
    include_methods: bool = True
    structured_payload_mode: Literal["out_of_band_only"] = "out_of_band_only"


class CompressionRulePredicate(ValueObject):
    """Predicate fields used to match compression rules."""

    tool_name: str | None = None
    tool_category: str | None = None
    command_signature: str | None = None
    command_prefix: str | None = None
    has_explicit_format: bool | None = None
    min_bytes: int | None = Field(default=None, ge=0)
    max_bytes: int | None = Field(default=None, ge=0)
    content_types: list[str] | None = None

    @field_validator("content_types", mode="before")
    @classmethod
    def _normalize_content_types(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip().lower()
            return [stripped] if stripped else None
        if not isinstance(value, list):
            return None
        out = [str(item).strip().lower() for item in value if str(item).strip()]
        return out or None


class CompressionRule(ValueObject):
    """Deterministic rule describing one strategy pipeline."""

    name: str
    priority: int = Field(default=1000, ge=0)
    when: CompressionRulePredicate = Field(default_factory=CompressionRulePredicate)
    pipeline: list[str] = Field(default_factory=list)

    @field_validator("pipeline", mode="before")
    @classmethod
    def _normalize_pipeline(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    normalized.append(stripped)
        return normalized


class OutputPatternRuleConfig(ValueObject):
    """Configurable full-output match replacement rule."""

    pattern: str
    message: str
    unless: str | None = None
    fallback_message: str = "tool: ok"

    @field_validator("pattern", "fallback_message")
    @classmethod
    def _required_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be empty")
        return normalized


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _default_method_states() -> dict[str, bool | Literal["inherit_legacy"]]:
    return {
        "ansi_normalize": True,
        "line_dedupe": True,
        "group_paths": True,
        "directory_tree_summary": True,
        "search_results_grouping": True,
        "file_detail_levels": True,
        "truncate_failure_preserving": True,
        "output_pattern_match": True,
        "diff_compact": True,
        "pytest_failure_focus": "inherit_legacy",
        "failure_focus_generic": True,
        "diagnostics_grouping": True,
        "json_ndjson_structural": True,
        "xml_machine_safeguard": True,
        "log_line_dedupe": True,
        "sensitive_field_projection": True,
    }


def _default_compression_rules() -> list[CompressionRule]:
    """Built-in rules so enabling dynamic compression reaches failure/diagnostic strategies."""
    return [
        CompressionRule(
            name="json_ndjson_structural",
            priority=8,
            when=CompressionRulePredicate(
                content_types=["json", "ndjson"],
                min_bytes=256,
                has_explicit_format=False,
            ),
            pipeline=["ansi_normalize", "json_ndjson_structural", "line_dedupe"],
        ),
        CompressionRule(
            name="xml_machine_safeguard",
            priority=8,
            when=CompressionRulePredicate(
                content_types=["xml"],
                min_bytes=256,
                has_explicit_format=False,
            ),
            pipeline=["ansi_normalize", "xml_machine_safeguard", "line_dedupe"],
        ),
        CompressionRule(
            name="sensitive_printenv",
            priority=9,
            when=CompressionRulePredicate(
                command_signature="printenv",
                content_types=["text"],
                has_explicit_format=False,
            ),
            pipeline=["sensitive_field_projection", "line_dedupe"],
        ),
        CompressionRule(
            name="sensitive_env_dump",
            priority=9,
            when=CompressionRulePredicate(
                command_signature="env",
                min_bytes=16,
                content_types=["text"],
                has_explicit_format=False,
            ),
            pipeline=["sensitive_field_projection", "line_dedupe"],
        ),
        CompressionRule(
            name="sensitive_aws",
            priority=9,
            when=CompressionRulePredicate(
                command_signature="aws",
                min_bytes=64,
                content_types=["text"],
                has_explicit_format=False,
            ),
            pipeline=["ansi_normalize", "sensitive_field_projection", "line_dedupe"],
        ),
        CompressionRule(
            name="sensitive_gcloud",
            priority=9,
            when=CompressionRulePredicate(
                command_signature="gcloud",
                min_bytes=64,
                content_types=["text"],
                has_explicit_format=False,
            ),
            pipeline=["ansi_normalize", "sensitive_field_projection", "line_dedupe"],
        ),
        CompressionRule(
            name="sensitive_terraform",
            priority=9,
            when=CompressionRulePredicate(
                command_signature="terraform",
                min_bytes=64,
                content_types=["text"],
                has_explicit_format=False,
            ),
            pipeline=["ansi_normalize", "sensitive_field_projection", "line_dedupe"],
        ),
        CompressionRule(
            name="docker_logs_dedupe",
            priority=42,
            when=CompressionRulePredicate(command_prefix="docker logs", min_bytes=2048),
            pipeline=["ansi_normalize", "log_line_dedupe", "line_dedupe"],
        ),
        CompressionRule(
            name="pytest_command",
            priority=15,
            when=CompressionRulePredicate(command_signature="pytest"),
            pipeline=["ansi_normalize", "pytest_failure_focus", "line_dedupe"],
        ),
        CompressionRule(
            name="python_pytest_heavy",
            priority=24,
            when=CompressionRulePredicate(command_signature="python", min_bytes=4096),
            pipeline=["ansi_normalize", "pytest_failure_focus"],
        ),
        CompressionRule(
            name="ruff_diagnostics",
            priority=18,
            when=CompressionRulePredicate(command_signature="ruff"),
            pipeline=["ansi_normalize", "diagnostics_grouping", "line_dedupe"],
        ),
        CompressionRule(
            name="mypy_diagnostics",
            priority=18,
            when=CompressionRulePredicate(command_signature="mypy"),
            pipeline=["ansi_normalize", "diagnostics_grouping", "line_dedupe"],
        ),
        CompressionRule(
            name="tsc_diagnostics",
            priority=18,
            when=CompressionRulePredicate(command_signature="tsc"),
            pipeline=["ansi_normalize", "diagnostics_grouping", "line_dedupe"],
        ),
        CompressionRule(
            name="cargo_outputs",
            priority=22,
            when=CompressionRulePredicate(command_signature="cargo"),
            pipeline=["ansi_normalize", "failure_focus_generic", "line_dedupe"],
        ),
        CompressionRule(
            name="npm_test_outputs",
            priority=23,
            when=CompressionRulePredicate(command_prefix="npm test"),
            pipeline=["ansi_normalize", "failure_focus_generic", "line_dedupe"],
        ),
    ]


class DynamicCompressionConfig(ValueObject):
    """Top-level dynamic compression configuration."""

    # Keep unknown keys accepted so runtime integrity checks can fail-open.
    model_config = ConfigDict(frozen=True, extra="allow")

    enabled: bool = False
    level: CompressionLevel = CompressionLevel.CONSERVATIVE
    max_level: CompressionLevel = CompressionLevel.AGGRESSIVE
    min_bytes: int = Field(default=1024, ge=0)
    time_budget_ms_per_output: int = Field(default=100, ge=1)
    explicit_format_flags: list[str] = Field(
        default_factory=lambda: [
            "--json",
            "--format",
            "--stat",
            "--numstat",
            "--shortstat",
            "--output-format",
        ]
    )
    marker: CompressionMarkerConfig = Field(default_factory=CompressionMarkerConfig)
    categories: dict[str, bool] = Field(
        default_factory=lambda: {
            "command_execution": True,
            "search": True,
            "list_dir": True,
            "file_read": True,
            "view_file": True,
            "test_execution": True,
            "other": True,
        }
    )
    methods: dict[str, bool | Literal["inherit_legacy"]] = Field(
        default_factory=_default_method_states
    )
    noise_directories: list[str] = Field(
        default_factory=lambda: [
            "node_modules",
            ".git",
            "target",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            "dist",
            "build",
            "vendor",
        ]
    )
    search_context_lines: int = Field(default=2, ge=0)
    search_max_matches_per_file: int = Field(default=8, ge=1)
    search_max_total_groups: int = Field(default=100, ge=1)
    search_max_line_length: int = Field(default=240, ge=20)
    file_detail_mode: Literal["auto", "full", "structure", "signatures"] = "auto"
    file_detail_fallback_mode: Literal["full", "structure", "signatures"] = "full"
    file_detail_auto_full_max_lines: int = Field(default=120, ge=1)
    file_detail_auto_structure_max_lines: int = Field(default=280, ge=1)
    file_detail_include_line_numbers: bool = False
    file_detail_max_lines: int | None = Field(default=None, ge=0)
    file_detail_last_n_lines: int | None = Field(default=None, ge=0)
    disable_categories: list[str] = Field(default_factory=list)
    disable_methods: list[str] = Field(default_factory=list)
    disable_tools: list[str] = Field(default_factory=list)
    disable_command_prefixes: list[str] = Field(default_factory=list)
    rules: list[CompressionRule] = Field(default_factory=_default_compression_rules)
    output_pattern_rules: list[OutputPatternRuleConfig] = Field(default_factory=list)
    output_pattern_regex_timeout_ms: int = Field(default=25, ge=1)
    diff_max_lines_per_hunk: int = Field(default=100, ge=1)
    diff_max_total_lines: int = Field(default=500, ge=10)
    json_structural_max_depth: int = Field(default=8, ge=1)
    json_structural_max_keys_per_object: int = Field(default=40, ge=1)
    json_structural_max_array_elements: int = Field(default=12, ge=1)
    json_structural_string_max_len: int = Field(default=120, ge=8)
    json_structural_min_bytes: int = Field(default=256, ge=0)
    xml_safeguard_text_max_len: int = Field(default=240, ge=16)
    xml_safeguard_min_bytes: int = Field(default=256, ge=0)
    log_dedupe_min_repeat: int = Field(default=4, ge=2)
    log_dedupe_min_bytes: int = Field(default=4096, ge=0)
    sensitive_projection_skip_prefixes: list[str] = Field(
        default_factory=lambda: ["printenv path", "printenv home"]
    )

    @field_validator(
        "explicit_format_flags",
        "noise_directories",
        "disable_categories",
        "disable_methods",
        "disable_tools",
        "disable_command_prefixes",
        "sensitive_projection_skip_prefixes",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _dedupe_preserve_order(
                [entry.strip() for entry in value.split(",") if entry.strip()]
            )
        if not isinstance(value, list):
            return []
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return _dedupe_preserve_order(normalized)

    def is_category_enabled(self, category: str) -> bool:
        normalized = category.strip().lower()
        if not normalized:
            return True
        if normalized in {entry.lower() for entry in self.disable_categories}:
            return False
        return bool(self.categories.get(normalized, True))

    def is_method_enabled(self, method_name: str) -> bool:
        normalized = method_name.strip()
        if not normalized:
            return False
        if normalized in self.disable_methods:
            return False
        state = self.methods.get(normalized, True)
        return bool(state is True or state == "inherit_legacy")
