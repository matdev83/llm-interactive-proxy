# Copyright 2025 Anthropic
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Property-based tests for LoggingConfigurator.

**Feature: cli-god-object-refactoring, Property 5: Timestamp Suffix Format Validity**

For any file path, applying `LoggingConfigurator.apply_timestamp_suffix` SHALL produce
a path matching the pattern `{stem}-YYYYMMDD_HHMM{suffix}` or return the original if
already suffixed.

Validates Requirements: 4.2, 4.4
"""

from __future__ import annotations

import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# Strategies for generating valid file paths
valid_stem_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)

# File stem: 1-100 valid characters, not starting with a dot
# Also filter out stems that look like they already have timestamp suffixes
file_stem_strategy = st.text(valid_stem_chars, min_size=1, max_size=100).filter(
    lambda s: not s.startswith(".") and not re.search(r"-\d{8}_\d{4}$", s)
)

# Common file extensions
extension_strategy = st.sampled_from([".log", ".cbor", ".txt", ".json", ""])

# Directory path components
directory_component_strategy = st.text(valid_stem_chars, min_size=1, max_size=20)

# YYYYMMDD_HHMM timestamp pattern for testing already-suffixed paths
timestamp_pattern = re.compile(r"^-\d{8}_\d{4}$")

# Pattern to match a valid timestamp suffix in a path
TIMESTAMP_SUFFIX_REGEX = re.compile(r"-\d{8}_\d{4}")


class TestTimestampSuffixFormatProperty:
    """Property tests validating timestamp suffix format.

    **Feature: cli-god-object-refactoring, Property 5: Timestamp Suffix Format Validity**
    """

    @given(stem=file_stem_strategy, ext=extension_strategy)
    @settings(max_examples=100, deadline=None)
    def test_apply_timestamp_suffix_produces_valid_format(
        self, stem: str, ext: str
    ) -> None:
        """**Property 5**: For any file path, timestamp suffix matches YYYYMMDD_HHMM pattern.

        GIVEN a valid file stem and extension
        WHEN apply_timestamp_suffix is called
        THEN the result matches {stem}-YYYYMMDD_HHMM{extension} pattern
        """
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        filename = f"{stem}{ext}"
        configurator = LoggingConfigurator()

        result = configurator.apply_timestamp_suffix(filename)

        assert result is not None, f"Expected non-None result for '{filename}'"

        # The result should contain a timestamp in YYYYMMDD_HHMM format
        match = TIMESTAMP_SUFFIX_REGEX.search(result)
        assert match is not None, f"No timestamp found in '{result}'"

        # Extract the timestamp and verify it matches expected format
        timestamp = match.group(0)[1:]  # Remove leading dash
        assert len(timestamp) == 13, f"Timestamp '{timestamp}' should be 13 chars"
        assert timestamp[8] == "_", "Timestamp should have underscore at position 8"

        # Verify the original extension is preserved
        if ext:
            assert result.endswith(
                ext
            ), f"Extension '{ext}' not preserved in '{result}'"

    @given(stem=file_stem_strategy, ext=extension_strategy)
    @settings(max_examples=100, deadline=None)
    def test_already_suffixed_path_not_double_suffixed(
        self, stem: str, ext: str
    ) -> None:
        """**Property 5**: Already-suffixed paths are returned unchanged.

        GIVEN a path that already has a timestamp suffix
        WHEN apply_timestamp_suffix is called
        THEN the original path is returned (no double-suffixing)
        """
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        # Create an already-suffixed path
        already_suffixed = f"{stem}-20251212_1430{ext}"
        configurator = LoggingConfigurator()

        result = configurator.apply_timestamp_suffix(already_suffixed)

        assert (
            result == already_suffixed
        ), f"Already-suffixed path should be unchanged: '{already_suffixed}' -> '{result}'"

    @given(
        dirs=st.lists(directory_component_strategy, min_size=0, max_size=5),
        stem=file_stem_strategy,
        ext=extension_strategy,
    )
    @settings(max_examples=100, deadline=None)
    def test_directory_structure_preserved(
        self, dirs: list[str], stem: str, ext: str
    ) -> None:
        """**Property 5**: Directory structure is preserved when applying timestamp suffix.

        GIVEN a path with directory components
        WHEN apply_timestamp_suffix is called
        THEN all directory components are preserved in the result
        """
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        # Build a path with directories
        if dirs:
            path = "/".join(dirs) + "/" + stem + ext
        else:
            path = stem + ext

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix(path)

        assert result is not None

        # All directory components should be present
        result_path = Path(result)
        original_path = Path(path)

        # The parent directories should match
        assert (
            result_path.parent == original_path.parent
        ), f"Directory structure not preserved: {original_path.parent} vs {result_path.parent}"

    @given(stem=file_stem_strategy, ext=extension_strategy)
    @settings(max_examples=100, deadline=None)
    def test_timestamp_represents_current_time(self, stem: str, ext: str) -> None:
        """**Property 5**: The timestamp in the suffix represents reasonable current time.

        GIVEN a file path
        WHEN apply_timestamp_suffix is called
        THEN the timestamp represents a valid date/time
        """

        from src.core.cli_support.logging_configurator import LoggingConfigurator

        filename = f"{stem}{ext}"
        configurator = LoggingConfigurator()

        result = configurator.apply_timestamp_suffix(filename)
        assert result is not None

        # Extract the timestamp
        match = TIMESTAMP_SUFFIX_REGEX.search(result)
        assert match is not None

        timestamp = match.group(0)[1:]  # Remove leading dash
        date_part = timestamp[:8]
        time_part = timestamp[9:]

        # Parse the timestamp components
        year = int(date_part[:4])
        month = int(date_part[4:6])
        day = int(date_part[6:8])
        hour = int(time_part[:2])
        minute = int(time_part[2:4])

        # Validate ranges (loose validation)
        assert 2020 <= year <= 2100, f"Year {year} out of reasonable range"
        assert 1 <= month <= 12, f"Month {month} out of range"
        assert 1 <= day <= 31, f"Day {day} out of range"
        assert 0 <= hour <= 23, f"Hour {hour} out of range"
        assert 0 <= minute <= 59, f"Minute {minute} out of range"


class TestNoneHandlingProperty:
    """Property tests for None and empty input handling."""

    @given(st.none())
    @settings(max_examples=10, deadline=None)
    def test_none_input_returns_none(self, _: None) -> None:
        """For None input, apply_timestamp_suffix returns None."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix(None)
        assert result is None

    @given(st.text(max_size=0))
    @settings(max_examples=10, deadline=None)
    def test_empty_string_returns_none(self, empty: str) -> None:
        """For empty string input, apply_timestamp_suffix returns None."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix(empty)
        assert result is None


class TestApplyPidSuffixesProperty:
    """Property tests for apply_pid_suffixes method."""

    @given(
        log_stem=file_stem_strategy,
        log_ext=st.just(".log"),
        has_capture=st.booleans(),
    )
    @settings(max_examples=50, deadline=None)
    def test_apply_pid_suffixes_adds_timestamps_consistently(
        self,
        log_stem: str,
        log_ext: str,
        has_capture: bool,
    ) -> None:
        """**Property 5**: apply_pid_suffixes consistently applies timestamps to all file paths.

        GIVEN an AppConfig with log_file and optionally capture_file
        WHEN apply_pid_suffixes is called
        THEN all file paths receive timestamp suffixes
        """
        from src.core.cli_support.logging_configurator import LoggingConfigurator
        from src.core.config.app_config import AppConfig

        log_file = f"var/logs/{log_stem}{log_ext}"
        logging_config: dict = {
            "log_file": log_file,
            "level": "DEBUG",
            "use_colors": True,
        }

        if has_capture:
            logging_config["capture_file"] = f"var/captures/{log_stem}.cbor"

        config = AppConfig(logging=logging_config)
        configurator = LoggingConfigurator()

        result = configurator.apply_pid_suffixes(config)

        # Log file should have timestamp
        assert result.logging.log_file is not None
        assert TIMESTAMP_SUFFIX_REGEX.search(
            result.logging.log_file
        ), f"No timestamp in log_file: {result.logging.log_file}"

        # If capture file was set, it should also have timestamp
        if has_capture:
            capture_file = getattr(result.logging, "capture_file", None)
            if capture_file:
                assert TIMESTAMP_SUFFIX_REGEX.search(
                    capture_file
                ), f"No timestamp in capture_file: {capture_file}"


class TestIdempotencyProperty:
    """Property tests for idempotency of timestamp suffix application."""

    @given(stem=file_stem_strategy, ext=extension_strategy)
    @settings(max_examples=50, deadline=None)
    def test_apply_timestamp_suffix_idempotent(self, stem: str, ext: str) -> None:
        """Applying timestamp suffix twice should not change the result after first application.

        This is an idempotency property - once a timestamp is added, adding it again
        should not modify the path.
        """
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        filename = f"{stem}{ext}"
        configurator = LoggingConfigurator()

        # First application
        result1 = configurator.apply_timestamp_suffix(filename)
        assert result1 is not None

        # Second application - should return the same result
        result2 = configurator.apply_timestamp_suffix(result1)
        assert (
            result2 == result1
        ), f"Second application should be idempotent: '{result1}' -> '{result2}'"


class TestConfigureProperty:
    """Property tests for configure method."""

    @given(
        log_level=st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
        use_colors=st.booleans(),
        has_log_file=st.booleans(),
    )
    @settings(max_examples=50, deadline=None)
    def test_configure_respects_all_settings(
        self,
        log_level: str,
        use_colors: bool,
        has_log_file: bool,
    ) -> None:
        """Configure method respects all logging settings from AppConfig.

        GIVEN various combinations of logging settings
        WHEN configure is called
        THEN all settings are passed to the underlying logging configuration
        """
        import logging as logging_module
        from unittest.mock import patch

        from src.core.cli_support.logging_configurator import LoggingConfigurator
        from src.core.config.app_config import AppConfig

        log_file = "test.log" if has_log_file else None
        config = AppConfig(
            logging={
                "log_file": log_file,
                "level": log_level,
                "use_colors": use_colors,
            }
        )

        configurator = LoggingConfigurator()

        expected_level = getattr(logging_module, log_level)

        with patch(
            "src.core.cli_support.logging_configurator.configure_logging_with_environment_tagging"
        ) as mock_configure:
            configurator.configure(config)

            mock_configure.assert_called_once()
            call_kwargs = mock_configure.call_args.kwargs

            assert call_kwargs["level"] == expected_level
            assert call_kwargs["log_file"] == log_file
            assert call_kwargs["use_colors"] == use_colors
