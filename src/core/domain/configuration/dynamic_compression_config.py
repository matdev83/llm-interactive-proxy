"""Domain configuration for dynamic tool-output compression."""

from __future__ import annotations

from enum import Enum
from typing import Literal, cast

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


class CompressionAlertsConfig(ValueObject):
    """Operator alert thresholds for frequent failures/fallbacks."""

    enabled: bool = True
    failure_threshold: int = Field(default=5, ge=1)
    fallback_threshold: int = Field(default=8, ge=1)
    window_seconds: int = Field(default=300, ge=1)
    cooldown_seconds: int = Field(default=300, ge=1)


class CompressionRecoveryConfig(ValueObject):
    """Bounded retention settings for truncation recovery artifacts."""

    mode: Literal["never", "failures", "always"] = "never"
    min_original_bytes: int = Field(default=4096, ge=0)
    min_saved_bytes: int = Field(default=2048, ge=0)
    max_artifact_bytes: int = Field(default=262_144, ge=128)
    max_artifacts: int = Field(default=128, ge=1)
    retention_seconds: int = Field(default=86_400, ge=1)
    storage_dir: str = "var/compression_recovery"
    hint_in_text: bool = False

    @field_validator("storage_dir")
    @classmethod
    def _normalize_storage_dir(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("storage_dir cannot be empty")
        return normalized


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
        out: list[str] = []
        for it in cast("list[object]", value):
            if isinstance(it, str) and it.strip():
                out.append(it.strip().lower())
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
        for candidate in cast("list[object]", value):
            if isinstance(candidate, str):
                stripped = candidate.strip()
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


def _dedupe_lower_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _default_method_states() -> dict[str, bool]:
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
        "mutating_success_ack": True,
        "stats_extraction_summary": True,
        "pytest_failure_focus": True,
        "failure_focus_generic": True,
        "diagnostics_grouping": True,
        "json_ndjson_structural": True,
        "xml_machine_safeguard": True,
        "log_line_dedupe": True,
        "sensitive_field_projection": True,
        "declarative_rule_filter": True,
        "git_status": True,
    }


def _builtin_git_mutating_rules() -> list[CompressionRule]:
    """Concise success acknowledgements for common mutating git subcommands."""
    pipeline = ["ansi_normalize", "mutating_success_ack", "line_dedupe"]
    prefixes = (
        "git add",
        "git commit",
        "git push",
        "git pull",
        "git fetch",
        "git merge",
        "git rebase",
        "git stash",
        "git cherry-pick",
        "git checkout",
        "git restore",
        "git rm",
        "git mv",
    )
    return [
        CompressionRule(
            name=f"git_mutating__{p.replace(' ', '_')}",
            priority=11,
            when=CompressionRulePredicate(
                command_prefix=p,
                command_signature="git",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=400,
            ),
            pipeline=list(pipeline),
        )
        for p in prefixes
    ]


def _builtin_tool_family_coverage_rules() -> list[CompressionRule]:
    """Default rule coverage for common CLI families (deterministic, text-only)."""
    af = ["ansi_normalize", "failure_focus_generic", "line_dedupe"]
    ad = ["ansi_normalize", "diagnostics_grouping", "line_dedupe"]
    stats_p = ["ansi_normalize", "stats_extraction_summary", "line_dedupe"]
    git_status_p = ["ansi_normalize", "git_status", "line_dedupe"]
    diff_p = ["ansi_normalize", "diff_compact", "line_dedupe"]

    rules: list[CompressionRule] = [
        CompressionRule(
            name="git_diff_compact",
            priority=10,
            when=CompressionRulePredicate(
                command_prefix="git diff",
                command_signature="git",
                content_types=["text"],
                has_explicit_format=False,
            ),
            pipeline=list(diff_p),
        ),
        CompressionRule(
            name="git_show_compact",
            priority=10,
            when=CompressionRulePredicate(
                command_prefix="git show",
                command_signature="git",
                content_types=["text"],
                has_explicit_format=False,
            ),
            pipeline=list(diff_p),
        ),
        CompressionRule(
            name="diff_command_compact",
            priority=10,
            when=CompressionRulePredicate(
                command_signature="diff",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=256,
            ),
            pipeline=list(diff_p),
        ),
        CompressionRule(
            name="git_status_structured",
            priority=12,
            when=CompressionRulePredicate(
                command_prefix="git status",
                command_signature="git",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=400,
            ),
            pipeline=list(git_status_p),
        ),
        CompressionRule(
            name="git_log_stats_first",
            priority=12,
            when=CompressionRulePredicate(
                command_prefix="git log",
                command_signature="git",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=400,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="git_branch_stats_first",
            priority=12,
            when=CompressionRulePredicate(
                command_prefix="git branch",
                command_signature="git",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=400,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="pip_list_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="pip list",
                command_signature="pip",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="pip_freeze_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="pip freeze",
                command_signature="pip",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="pip3_list_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="pip3 list",
                command_signature="pip3",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="npm_ls_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="npm ls",
                command_signature="npm",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="npm_list_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="npm list",
                command_signature="npm",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="pnpm_list_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="pnpm list",
                command_signature="pnpm",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="poetry_show_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="poetry show",
                command_signature="poetry",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="uv_pip_list_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="uv pip list",
                command_signature="uv",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="uv_pip_freeze_stats_first",
            priority=13,
            when=CompressionRulePredicate(
                command_prefix="uv pip freeze",
                command_signature="uv",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(stats_p),
        ),
        CompressionRule(
            name="brew_outputs",
            priority=27,
            when=CompressionRulePredicate(
                command_signature="brew",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="bundle_outputs",
            priority=27,
            when=CompressionRulePredicate(
                command_signature="bundle",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="composer_outputs",
            priority=27,
            when=CompressionRulePredicate(
                command_signature="composer",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="patch_outputs",
            priority=27,
            when=CompressionRulePredicate(
                command_signature="patch",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="rg_search_grouping",
            priority=14,
            when=CompressionRulePredicate(
                command_signature="rg",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=["ansi_normalize", "search_results_grouping", "line_dedupe"],
        ),
        CompressionRule(
            name="grep_search_grouping",
            priority=14,
            when=CompressionRulePredicate(
                command_signature="grep",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=["ansi_normalize", "search_results_grouping", "line_dedupe"],
        ),
        CompressionRule(
            name="tree_listing_summary",
            priority=14,
            when=CompressionRulePredicate(
                command_signature="tree",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=["ansi_normalize", "directory_tree_summary", "line_dedupe"],
        ),
        CompressionRule(
            name="ls_listing_summary",
            priority=14,
            when=CompressionRulePredicate(
                command_signature="ls",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=["ansi_normalize", "directory_tree_summary", "line_dedupe"],
        ),
        CompressionRule(
            name="eslint_diagnostics",
            priority=16,
            when=CompressionRulePredicate(
                command_signature="eslint",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(ad),
        ),
        CompressionRule(
            name="rubocop_diagnostics",
            priority=16,
            when=CompressionRulePredicate(
                command_signature="rubocop",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(ad),
        ),
        CompressionRule(
            name="golangci_lint_diagnostics",
            priority=16,
            when=CompressionRulePredicate(
                command_signature="golangci-lint",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(ad),
        ),
        CompressionRule(
            name="clippy_outputs",
            priority=16,
            when=CompressionRulePredicate(
                command_prefix="cargo clippy",
                command_signature="cargo",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="go_test_outputs",
            priority=17,
            when=CompressionRulePredicate(
                command_prefix="go test",
                command_signature="go",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="vitest_outputs",
            priority=17,
            when=CompressionRulePredicate(
                command_signature="vitest",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="playwright_test_outputs",
            priority=17,
            when=CompressionRulePredicate(
                command_prefix="npx playwright",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="make_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_signature="make",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="gradle_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_signature="gradle",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="gradlew_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_signature="gradlew",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="mvn_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_signature="mvn",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="dotnet_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_signature="dotnet",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="gcc_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_signature="gcc",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="clang_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_signature="clang",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="swift_build_outputs",
            priority=25,
            when=CompressionRulePredicate(
                command_prefix="swift build",
                command_signature="swift",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="black_formatter_outputs",
            priority=26,
            when=CompressionRulePredicate(
                command_signature="black",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="prettier_formatter_outputs",
            priority=26,
            when=CompressionRulePredicate(
                command_signature="prettier",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="biome_formatter_outputs",
            priority=26,
            when=CompressionRulePredicate(
                command_signature="biome",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="ruff_format_outputs",
            priority=17,
            when=CompressionRulePredicate(
                command_prefix="ruff format",
                command_signature="ruff",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="docker_cli_text",
            priority=28,
            when=CompressionRulePredicate(
                command_signature="docker",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="kubectl_cli_text",
            priority=28,
            when=CompressionRulePredicate(
                command_signature="kubectl",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="gh_cli_text",
            priority=28,
            when=CompressionRulePredicate(
                command_signature="gh",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="helm_cli_text",
            priority=28,
            when=CompressionRulePredicate(
                command_signature="helm",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="ansible_playbook_text",
            priority=28,
            when=CompressionRulePredicate(
                command_signature="ansible-playbook",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="curl_http_text",
            priority=30,
            when=CompressionRulePredicate(
                command_signature="curl",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=4096,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="wget_http_text",
            priority=30,
            when=CompressionRulePredicate(
                command_signature="wget",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=4096,
            ),
            pipeline=list(af),
        ),
        CompressionRule(
            name="psql_cli_text",
            priority=31,
            when=CompressionRulePredicate(
                command_signature="psql",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=2048,
            ),
            pipeline=list(af),
        ),
    ]
    return rules


def _builtin_tool_category_coverage_rules() -> list[CompressionRule]:
    """Category defaults for non-shell tool families."""
    return [
        CompressionRule(
            name="category_search_grouping",
            priority=320,
            when=CompressionRulePredicate(
                tool_category="search",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=["ansi_normalize", "search_results_grouping", "line_dedupe"],
        ),
        CompressionRule(
            name="category_list_dir_summary",
            priority=321,
            when=CompressionRulePredicate(
                tool_category="list_dir",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=["ansi_normalize", "directory_tree_summary", "line_dedupe"],
        ),
        CompressionRule(
            name="category_file_read_details",
            priority=322,
            when=CompressionRulePredicate(
                tool_category="file_read",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=["ansi_normalize", "file_detail_levels", "line_dedupe"],
        ),
        CompressionRule(
            name="category_view_file_details",
            priority=323,
            when=CompressionRulePredicate(
                tool_category="view_file",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=512,
            ),
            pipeline=["ansi_normalize", "file_detail_levels", "line_dedupe"],
        ),
        CompressionRule(
            name="category_test_execution_failure_focus",
            priority=324,
            when=CompressionRulePredicate(
                tool_category="test_execution",
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=1024,
            ),
            pipeline=["ansi_normalize", "failure_focus_generic", "line_dedupe"],
        ),
    ]


def _builtin_generic_fallback_rules() -> list[CompressionRule]:
    """Low-priority deterministic fallback for plain-text outputs."""
    return [
        CompressionRule(
            name="generic_text_fallback",
            priority=999,
            when=CompressionRulePredicate(
                content_types=["text"],
                has_explicit_format=False,
                min_bytes=256,
            ),
            pipeline=["ansi_normalize", "failure_focus_generic", "line_dedupe"],
        )
    ]


def _default_compression_rules() -> list[CompressionRule]:
    """Built-in rules so enabling dynamic compression reaches failure/diagnostic strategies."""
    return [
        *[
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
                pipeline=[
                    "ansi_normalize",
                    "sensitive_field_projection",
                    "line_dedupe",
                ],
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
                pipeline=[
                    "ansi_normalize",
                    "sensitive_field_projection",
                    "line_dedupe",
                ],
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
                pipeline=[
                    "ansi_normalize",
                    "sensitive_field_projection",
                    "line_dedupe",
                ],
            ),
            CompressionRule(
                name="docker_logs_dedupe",
                priority=42,
                when=CompressionRulePredicate(
                    command_prefix="docker logs", min_bytes=2048
                ),
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
                when=CompressionRulePredicate(
                    command_signature="python", min_bytes=4096
                ),
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
        ],
        *_builtin_git_mutating_rules(),
        *_builtin_tool_family_coverage_rules(),
        *_builtin_tool_category_coverage_rules(),
        *_builtin_generic_fallback_rules(),
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
    telemetry_include_content_hashes: bool = True
    per_output_evaluation_log_level: Literal["off", "debug", "info"] = "debug"
    marker: CompressionMarkerConfig = Field(default_factory=CompressionMarkerConfig)
    alerts: CompressionAlertsConfig = Field(default_factory=CompressionAlertsConfig)
    recovery: CompressionRecoveryConfig = Field(
        default_factory=CompressionRecoveryConfig
    )
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
    methods: dict[str, bool] = Field(default_factory=_default_method_states)
    pytest_failure_focus_min_lines: int | None = Field(default=None, ge=0)
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
    disable_tools: list[str] = Field(default_factory=lambda: ["read", "read_file"])
    disable_tool_name_substrings: list[str] = Field(default_factory=list)
    disable_command_prefixes: list[str] = Field(default_factory=list)
    rules: list[CompressionRule] = Field(default_factory=_default_compression_rules)
    output_pattern_rules: list[OutputPatternRuleConfig] = Field(default_factory=list)
    output_pattern_regex_timeout_ms: int = Field(default=25, ge=1)
    declarative_rules: list[dict[str, object]] = Field(default_factory=list)
    declarative_rule_files: list[str] = Field(default_factory=list)
    declarative_regex_timeout_ms: int = Field(default=25, ge=1)
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
        "disable_tool_name_substrings",
        "disable_command_prefixes",
        "sensitive_projection_skip_prefixes",
        "declarative_rule_files",
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
        normalized: list[str] = []
        for it in cast("list[object]", value):
            if isinstance(it, str) and it.strip():
                normalized.append(it.strip())
        return _dedupe_preserve_order(normalized)

    @field_validator("pytest_failure_focus_min_lines", mode="before")
    @classmethod
    def _reject_boolean_pytest_failure_focus_min_lines(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, bool):
            raise ValueError("pytest_failure_focus_min_lines must be an integer")
        return value

    @field_validator("disable_command_prefixes")
    @classmethod
    def _normalize_disable_command_prefixes(cls, value: list[str]) -> list[str]:
        return _dedupe_lower_preserve_order(value)

    @field_validator("disable_tool_name_substrings")
    @classmethod
    def _normalize_disable_tool_name_substrings(cls, value: list[str]) -> list[str]:
        return _dedupe_lower_preserve_order(value)

    @field_validator("declarative_rules", mode="before")
    @classmethod
    def _normalize_declarative_rules(cls, value: object) -> list[dict[str, object]]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [cast("dict[str, object]", value)]
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, object]] = []
        for candidate in cast("list[object]", value):
            if isinstance(candidate, dict):
                normalized.append(cast("dict[str, object]", candidate))
        return normalized

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
        return bool(state is True)
