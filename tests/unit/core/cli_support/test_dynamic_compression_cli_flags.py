from __future__ import annotations

from src.core.cli_support.argument_parser_builder import ArgumentParserBuilder


def _collect_flags() -> set[str]:
    parser = ArgumentParserBuilder().build()
    flags: set[str] = set()
    for action in parser._actions:
        for option in action.option_strings:
            flags.add(option)
    return flags


def test_dynamic_compression_flags_are_registered() -> None:
    flags = _collect_flags()
    assert "--enable-dynamic-compression" in flags
    assert "--dynamic-compression-level" in flags
    assert "--dynamic-compression-max-level" in flags
    assert "--dynamic-compression-min-bytes" in flags
    assert "--dynamic-compression-per-output-evaluation-log-level" in flags
    assert "--dynamic-compression-file-detail-include-line-numbers" in flags
    assert "--dynamic-compression-file-detail-exclude-line-numbers" in flags
    assert "--dynamic-compression-disable-categories" in flags
    assert "--dynamic-compression-disable-methods" in flags
    assert "--dynamic-compression-disable-tools" in flags
    assert "--dynamic-compression-disable-command-prefixes" in flags
