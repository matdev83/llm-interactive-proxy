"""Unit tests for DynamicCompressionApplicator."""

from __future__ import annotations

import argparse
from typing import cast

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def _empty_args() -> argparse.Namespace:
    return argparse.Namespace(
        enable_dynamic_compression=None,
        dynamic_compression_level=None,
        dynamic_compression_max_level=None,
        dynamic_compression_min_bytes=None,
        dynamic_compression_per_output_evaluation_log_level=None,
        dynamic_compression_file_detail_include_line_numbers=None,
        dynamic_compression_disable_categories=None,
        dynamic_compression_disable_methods=None,
        dynamic_compression_disable_tools=None,
        dynamic_compression_disable_tool_name_substrings=None,
        dynamic_compression_disable_command_prefixes=None,
    )


def test_dynamic_compression_applicator_sets_overrides_and_resolution() -> None:
    from src.core.cli_support.applicators.dynamic_compression_applicator import (
        DynamicCompressionApplicator,
    )

    args = _empty_args()
    args.enable_dynamic_compression = True
    args.dynamic_compression_level = "balanced"
    args.dynamic_compression_max_level = "aggressive"
    args.dynamic_compression_min_bytes = 2048
    args.dynamic_compression_per_output_evaluation_log_level = "off"
    args.dynamic_compression_file_detail_include_line_numbers = True
    args.dynamic_compression_disable_methods = "ansi_normalize,line_dedupe"

    overrides: dict[str, object] = {}
    resolution = ParameterResolution()

    DynamicCompressionApplicator().apply(args, overrides, resolution)

    dc = overrides.get("dynamic_compression")
    assert isinstance(dc, dict)
    dc_typed = cast("dict[str, object]", dc)
    assert dc_typed.get("enabled") is True
    assert dc_typed.get("level") == "balanced"
    assert dc_typed.get("max_level") == "aggressive"
    assert dc_typed.get("min_bytes") == 2048
    assert dc_typed.get("per_output_evaluation_log_level") == "off"
    assert dc_typed.get("file_detail_include_line_numbers") is True
    assert dc_typed.get("disable_methods") == ["ansi_normalize", "line_dedupe"]

    cli_paths = set(resolution.latest_by_source(ParameterSource.CLI))
    assert "dynamic_compression.enabled" in cli_paths
    assert "dynamic_compression.level" in cli_paths
    assert "dynamic_compression.max_level" in cli_paths
    assert "dynamic_compression.min_bytes" in cli_paths
    assert "dynamic_compression.per_output_evaluation_log_level" in cli_paths
    assert "dynamic_compression.file_detail_include_line_numbers" in cli_paths
    assert "dynamic_compression.disable_methods" in cli_paths


def test_dynamic_compression_applicator_is_noop_when_no_args() -> None:
    from src.core.cli_support.applicators.dynamic_compression_applicator import (
        DynamicCompressionApplicator,
    )

    overrides: dict[str, object] = {}
    resolution = ParameterResolution()
    DynamicCompressionApplicator().apply(_empty_args(), overrides, resolution)

    assert overrides == {}
    assert not resolution.latest_by_source(ParameterSource.CLI)
