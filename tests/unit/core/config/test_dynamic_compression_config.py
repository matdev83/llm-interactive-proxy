from __future__ import annotations

from src.core.config.app_config import AppConfig
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContentType, ToolOutputContext
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector


def _tool_output_context(
    *,
    command_signature: str | None,
    command_prefix: str | None = None,
    tool_name: str = "shell",
    tool_category: str = "command_execution",
    content: str,
    content_type: ToolOutputContentType = ToolOutputContentType.TEXT,
    has_explicit_format: bool = False,
) -> ToolOutputContext:
    context = ToolOutputContext.for_text(
        tool_name=tool_name,
        tool_category=tool_category,
        content=content,
        command_signature=command_signature,
        command_prefix=(
            command_prefix if command_prefix is not None else command_signature
        ),
    )
    return context.model_copy(
        update={
            "content_type": content_type,
            "has_explicit_format": has_explicit_format,
            "is_machine_parseable": content_type
            in {
                ToolOutputContentType.JSON,
                ToolOutputContentType.NDJSON,
                ToolOutputContentType.XML,
            },
        }
    )


def test_dynamic_compression_defaults_are_safe() -> None:
    cfg = DynamicCompressionConfig()

    assert cfg.enabled is False
    assert cfg.level == CompressionLevel.CONSERVATIVE
    assert cfg.max_level == CompressionLevel.AGGRESSIVE
    assert cfg.min_bytes == 1024
    assert cfg.marker.enabled is True
    assert cfg.marker.structured_payload_mode == "out_of_band_only"


def test_dynamic_compression_defaults_include_rtk_generic_primitives() -> None:
    cfg = DynamicCompressionConfig()

    assert cfg.methods["group_paths"] is True
    assert cfg.methods["failure_focus_generic"] is True
    assert cfg.methods["diagnostics_grouping"] is True
    assert cfg.methods["json_ndjson_structural"] is True
    assert cfg.methods["xml_machine_safeguard"] is True
    assert cfg.methods["log_line_dedupe"] is True
    assert cfg.methods["sensitive_field_projection"] is True
    assert cfg.methods["output_pattern_match"] is True
    assert cfg.methods["diff_compact"] is True
    assert cfg.methods["mutating_success_ack"] is True
    assert cfg.methods["stats_extraction_summary"] is True
    assert cfg.methods["directory_tree_summary"] is True
    assert cfg.methods["search_results_grouping"] is True
    assert cfg.methods["file_detail_levels"] is True
    assert "node_modules" in cfg.noise_directories
    assert cfg.search_context_lines == 2
    assert cfg.search_max_matches_per_file == 8
    assert cfg.file_detail_mode == "auto"
    assert cfg.file_detail_fallback_mode == "full"
    assert cfg.file_detail_include_line_numbers is False
    assert cfg.output_pattern_regex_timeout_ms == 25
    assert cfg.diff_max_lines_per_hunk == 100
    assert cfg.diff_max_total_lines == 500
    assert len(cfg.rules) >= 1
    rule_names = {rule.name for rule in cfg.rules}
    assert "pytest_command" in rule_names
    assert "cargo_outputs" in rule_names
    assert "json_ndjson_structural" in rule_names
    assert "xml_machine_safeguard" in rule_names
    assert "git_status_stats_first" in rule_names
    assert "git_diff_compact" in rule_names
    assert "diff_command_compact" in rule_names
    assert any(name.startswith("git_mutating__") for name in rule_names)
    assert "rg_search_grouping" in rule_names
    assert "docker_cli_text" in rule_names
    assert "brew_outputs" in rule_names
    assert "bundle_outputs" in rule_names
    assert "composer_outputs" in rule_names
    assert "patch_outputs" in rule_names
    assert "category_search_grouping" in rule_names
    assert "category_list_dir_summary" in rule_names
    assert "category_file_read_details" in rule_names
    assert "category_view_file_details" in rule_names
    assert "generic_text_fallback" in rule_names


def test_default_generic_fallback_rule_selects_unknown_command_signature() -> None:
    cfg = DynamicCompressionConfig(enabled=True)
    selector = RuleBasedStrategySelector()
    context = _tool_output_context(
        command_signature="customcli",
        command_prefix="customcli run heavy-task",
        content=("repeat this line\n" * 128),
    )

    selected = selector.select_rule(context, cfg)
    assert selected is not None
    assert selected.name == "generic_text_fallback"


def test_default_category_rules_cover_non_shell_tool_families() -> None:
    cfg = DynamicCompressionConfig(enabled=True)
    selector = RuleBasedStrategySelector()
    payload = ("line\n" * 160) + "tail\n"
    expected = {
        "search": "category_search_grouping",
        "list_dir": "category_list_dir_summary",
        "file_read": "category_file_read_details",
        "view_file": "category_view_file_details",
    }

    for tool_category, expected_rule in expected.items():
        context = _tool_output_context(
            tool_name=tool_category,
            tool_category=tool_category,
            command_signature=None,
            command_prefix=None,
            content=payload,
        )
        selected = selector.select_rule(context, cfg)
        assert selected is not None
        assert selected.name == expected_rule


def test_default_missing_family_rules_cover_task_list_families() -> None:
    cfg = DynamicCompressionConfig(enabled=True)
    selector = RuleBasedStrategySelector()
    payload = ("diagnostic line\n" * 160) + "done\n"
    cases = {
        ("brew", "brew install ripgrep"): "brew_outputs",
        ("bundle", "bundle install"): "bundle_outputs",
        ("composer", "composer install"): "composer_outputs",
        ("patch", "patch -p1 < update.patch"): "patch_outputs",
    }

    for (signature, prefix), expected_rule in cases.items():
        context = _tool_output_context(
            command_signature=signature,
            command_prefix=prefix,
            content=payload,
        )
        selected = selector.select_rule(context, cfg)
        assert selected is not None
        assert selected.name == expected_rule

    diff_context = _tool_output_context(
        command_signature="diff",
        command_prefix="diff -u old.txt new.txt",
        content=(
            "--- old.txt\n+++ new.txt\n@@ -1,1 +1,2 @@\n-old\n+new\n+extra\n" * 40
        ),
    )
    selected_diff = selector.select_rule(diff_context, cfg)
    assert selected_diff is not None
    assert selected_diff.name == "diff_command_compact"


def test_disable_command_prefixes_are_case_insensitive_and_deterministic() -> None:
    cfg = DynamicCompressionConfig(
        disable_command_prefixes=[
            "Git Status",
            "git status",
            " GIT STATUS ",
            "GIT DIFF --STAT",
        ]
    )

    assert cfg.disable_command_prefixes == [
        "git status",
        "git diff --stat",
    ]


def test_default_sensitive_rules_require_text_and_non_explicit_format() -> None:
    cfg = DynamicCompressionConfig()
    rules_by_name = {rule.name: rule for rule in cfg.rules}
    sensitive_rule_names = {
        "sensitive_printenv",
        "sensitive_env_dump",
        "sensitive_aws",
        "sensitive_gcloud",
        "sensitive_terraform",
    }

    for rule_name in sensitive_rule_names:
        predicate = rules_by_name[rule_name].when
        assert predicate.content_types == ["text"]
        assert predicate.has_explicit_format is False


def test_default_sensitive_rule_selection_keeps_expected_text_coverage() -> None:
    cfg = DynamicCompressionConfig(enabled=True)
    selector = RuleBasedStrategySelector()
    content = "API_KEY=" + ("x" * 128)
    expected = {
        "printenv": "sensitive_printenv",
        "env": "sensitive_env_dump",
        "aws": "sensitive_aws",
        "gcloud": "sensitive_gcloud",
        "terraform": "sensitive_terraform",
    }

    for command_signature, expected_rule in expected.items():
        context = _tool_output_context(
            command_signature=command_signature,
            content=content,
        )
        selected = selector.select_rule(context, cfg)
        assert selected is not None
        assert selected.name == expected_rule


def test_default_sensitive_rules_skip_explicit_and_structured_contexts() -> None:
    cfg = DynamicCompressionConfig(enabled=True)
    selector = RuleBasedStrategySelector()
    command_signatures = ("printenv", "env", "aws", "gcloud", "terraform")
    explicit_text = "TOKEN=" + ("x" * 128)
    structured_payload = '{"token":"' + ("x" * 96) + '"}'

    for command_signature in command_signatures:
        explicit_context = _tool_output_context(
            command_signature=command_signature,
            content=explicit_text,
            has_explicit_format=True,
        )
        assert selector.select_rule(explicit_context, cfg) is None

        structured_context = _tool_output_context(
            command_signature=command_signature,
            content=structured_payload,
            content_type=ToolOutputContentType.JSON,
        )
        assert selector.select_rule(structured_context, cfg) is None


def test_app_config_accepts_dynamic_compression_block() -> None:
    app_cfg = AppConfig.model_validate(
        {
            "dynamic_compression": {
                "enabled": True,
                "level": "balanced",
                "max_level": "aggressive",
                "min_bytes": 256,
                "file_detail_include_line_numbers": True,
                "disable_categories": ["search"],
                "disable_methods": ["line_dedupe"],
                "disable_tools": ["shell"],
                "disable_command_prefixes": ["git diff --stat"],
            }
        }
    )

    dc = app_cfg.dynamic_compression
    assert dc.enabled is True
    assert dc.level == CompressionLevel.BALANCED
    assert dc.max_level == CompressionLevel.AGGRESSIVE
    assert dc.min_bytes == 256
    assert dc.file_detail_include_line_numbers is True
    assert dc.disable_categories == ["search"]
    assert dc.disable_methods == ["line_dedupe"]
    assert dc.disable_tools == ["shell"]
    assert dc.disable_command_prefixes == ["git diff --stat"]


def test_dynamic_compression_env_is_loaded_and_tracked() -> None:
    resolution = ParameterResolution()
    cfg = AppConfig.from_env(
        environ={
            "ENABLE_DYNAMIC_COMPRESSION": "true",
            "DYNAMIC_COMPRESSION_LEVEL": "balanced",
            "DYNAMIC_COMPRESSION_MAX_LEVEL": "aggressive",
            "DYNAMIC_COMPRESSION_MIN_BYTES": "512",
            "DYNAMIC_COMPRESSION_FILE_DETAIL_INCLUDE_LINE_NUMBERS": "true",
            "DYNAMIC_COMPRESSION_DISABLE_METHODS": "ansi_normalize,line_dedupe",
        },
        resolution=resolution,
    )

    assert cfg.dynamic_compression.enabled is True
    assert cfg.dynamic_compression.level == CompressionLevel.BALANCED
    assert cfg.dynamic_compression.max_level == CompressionLevel.AGGRESSIVE
    assert cfg.dynamic_compression.min_bytes == 512
    assert cfg.dynamic_compression.file_detail_include_line_numbers is True
    assert cfg.dynamic_compression.disable_methods == [
        "ansi_normalize",
        "line_dedupe",
    ]

    env_paths = set(resolution.latest_by_source(ParameterSource.ENVIRONMENT))
    assert "dynamic_compression.enabled" in env_paths
    assert "dynamic_compression.level" in env_paths
    assert "dynamic_compression.max_level" in env_paths
    assert "dynamic_compression.min_bytes" in env_paths
    assert "dynamic_compression.file_detail_include_line_numbers" in env_paths
    assert "dynamic_compression.disable_methods" in env_paths
