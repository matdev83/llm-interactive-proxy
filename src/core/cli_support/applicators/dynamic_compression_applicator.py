"""DynamicCompressionApplicator - applies dynamic compression CLI overrides."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


def _parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed


class DynamicCompressionApplicator:
    """Apply dynamic compression flags into top-level config overrides."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        dynamic_overrides: dict[str, Any] = {}

        if getattr(args, "enable_dynamic_compression", None) is not None:
            dynamic_overrides["enabled"] = args.enable_dynamic_compression
            resolution.record(
                "dynamic_compression.enabled",
                args.enable_dynamic_compression,
                ParameterSource.CLI,
                origin="--enable-dynamic-compression",
            )

        if getattr(args, "dynamic_compression_level", None) is not None:
            dynamic_overrides["level"] = args.dynamic_compression_level
            resolution.record(
                "dynamic_compression.level",
                args.dynamic_compression_level,
                ParameterSource.CLI,
                origin="--dynamic-compression-level",
            )

        if getattr(args, "dynamic_compression_max_level", None) is not None:
            dynamic_overrides["max_level"] = args.dynamic_compression_max_level
            resolution.record(
                "dynamic_compression.max_level",
                args.dynamic_compression_max_level,
                ParameterSource.CLI,
                origin="--dynamic-compression-max-level",
            )

        if getattr(args, "dynamic_compression_min_bytes", None) is not None:
            dynamic_overrides["min_bytes"] = args.dynamic_compression_min_bytes
            resolution.record(
                "dynamic_compression.min_bytes",
                args.dynamic_compression_min_bytes,
                ParameterSource.CLI,
                origin="--dynamic-compression-min-bytes",
            )

        if (
            getattr(args, "dynamic_compression_per_output_evaluation_log_level", None)
            is not None
        ):
            dynamic_overrides["per_output_evaluation_log_level"] = (
                args.dynamic_compression_per_output_evaluation_log_level
            )
            resolution.record(
                "dynamic_compression.per_output_evaluation_log_level",
                args.dynamic_compression_per_output_evaluation_log_level,
                ParameterSource.CLI,
                origin="--dynamic-compression-per-output-evaluation-log-level",
            )

        if (
            getattr(args, "dynamic_compression_file_detail_include_line_numbers", None)
            is not None
        ):
            dynamic_overrides["file_detail_include_line_numbers"] = (
                args.dynamic_compression_file_detail_include_line_numbers
            )
            resolution.record(
                "dynamic_compression.file_detail_include_line_numbers",
                args.dynamic_compression_file_detail_include_line_numbers,
                ParameterSource.CLI,
                origin=(
                    "--dynamic-compression-file-detail-include-line-numbers"
                    if args.dynamic_compression_file_detail_include_line_numbers
                    else "--dynamic-compression-file-detail-exclude-line-numbers"
                ),
            )

        list_flag_mappings = {
            "dynamic_compression_disable_categories": (
                "disable_categories",
                "dynamic_compression.disable_categories",
                "--dynamic-compression-disable-categories",
            ),
            "dynamic_compression_disable_methods": (
                "disable_methods",
                "dynamic_compression.disable_methods",
                "--dynamic-compression-disable-methods",
            ),
            "dynamic_compression_disable_tools": (
                "disable_tools",
                "dynamic_compression.disable_tools",
                "--dynamic-compression-disable-tools",
            ),
            "dynamic_compression_disable_command_prefixes": (
                "disable_command_prefixes",
                "dynamic_compression.disable_command_prefixes",
                "--dynamic-compression-disable-command-prefixes",
            ),
            "dynamic_compression_disable_tool_name_substrings": (
                "disable_tool_name_substrings",
                "dynamic_compression.disable_tool_name_substrings",
                "--dynamic-compression-disable-tool-name-substrings",
            ),
        }
        for attr_name, (
            target_key,
            resolution_path,
            origin,
        ) in list_flag_mappings.items():
            raw_value = getattr(args, attr_name, None)
            parsed = _parse_csv(raw_value)
            if parsed is None:
                continue
            dynamic_overrides[target_key] = parsed
            resolution.record(
                resolution_path,
                parsed,
                ParameterSource.CLI,
                origin=origin,
            )

        if dynamic_overrides:
            overrides["dynamic_compression"] = dynamic_overrides
