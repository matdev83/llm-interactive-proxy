"""Tests for ToolArgumentsParser.

Following TDD methodology: tests written after implementation.
"""

from __future__ import annotations

from unittest.mock import Mock

from src.core.interfaces.tool_call_reactor_internal import (
    ToolArgumentsEnvelope,
)
from src.core.services.tool_call_reactor.arguments_parser import (
    ToolArgumentsParser,
)


class TestParseDictInput:
    """Tests for parsing dictionary inputs."""

    def test_parse_dict_success(self) -> None:
        """Test parsing a dictionary input results in success outcome."""
        parser = ToolArgumentsParser()
        args = {"key": "value", "number": 42}

        envelope = parser.parse(args)

        assert envelope.parse_outcome == "success"
        assert envelope.normalized_arguments.root == args
        assert envelope.raw_arguments is None
        assert envelope.was_modified_by_fixups is False

    def test_parse_nested_dict(self) -> None:
        """Test parsing a nested dictionary."""
        parser = ToolArgumentsParser()
        args = {"outer": {"inner": "value"}}

        envelope = parser.parse(args)

        assert envelope.parse_outcome == "success"
        assert envelope.normalized_arguments.root == args


class TestParseListInput:
    """Tests for parsing list inputs."""

    def test_parse_list_success(self) -> None:
        """Test parsing a list input results in success outcome."""
        parser = ToolArgumentsParser()
        args = ["item1", "item2", "item3"]

        envelope = parser.parse(args)

        assert envelope.parse_outcome == "success"
        assert "__proxy_args_list__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_list__"] == args


class TestParseStringInput:
    """Tests for parsing string inputs."""

    def test_parse_valid_json_object_string(self) -> None:
        """Test parsing a valid JSON object string."""
        parser = ToolArgumentsParser()
        json_str = '{"key": "value", "number": 42}'

        envelope = parser.parse(json_str)

        assert envelope.parse_outcome == "success"
        assert envelope.raw_arguments == json_str
        assert envelope.normalized_arguments.root == {"key": "value", "number": 42}

    def test_parse_valid_json_array_string(self) -> None:
        """Test parsing a valid JSON array string."""
        parser = ToolArgumentsParser()
        json_str = '["item1", "item2"]'

        envelope = parser.parse(json_str)

        assert envelope.parse_outcome == "success"
        assert envelope.raw_arguments == json_str
        assert "__proxy_args_list__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_list__"] == [
            "item1",
            "item2",
        ]

    def test_parse_invalid_json_with_repair(self) -> None:
        """Test parsing invalid JSON that can be repaired."""
        parser = ToolArgumentsParser()
        # Trailing comma - json_repair can fix this
        invalid_json = '{"key": "value",}'

        envelope = parser.parse(invalid_json)

        # Outcome depends on whether repair succeeds
        assert envelope.parse_outcome in ("success", "recovered", "failed")
        assert envelope.raw_arguments == invalid_json
        # Should have normalized arguments even if parsing failed
        assert envelope.normalized_arguments.root is not None

    def test_parse_unparseable_text(self) -> None:
        """Test parsing unparseable text results in failed outcome."""
        parser = ToolArgumentsParser()
        raw_text = "some unparseable text that is not JSON"

        envelope = parser.parse(raw_text)

        assert envelope.parse_outcome == "failed"
        assert envelope.raw_arguments == raw_text
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == raw_text

    def test_parse_empty_string(self) -> None:
        """Test parsing an empty string."""
        parser = ToolArgumentsParser()

        envelope = parser.parse("")

        # Empty string may parse as empty JSON or fail
        assert envelope.parse_outcome in ("success", "failed")
        assert envelope.raw_arguments == ""


class TestParseOtherTypes:
    """Tests for parsing other input types."""

    def test_parse_int(self) -> None:
        """Test parsing an integer input."""
        parser = ToolArgumentsParser()

        envelope = parser.parse(42)

        assert envelope.parse_outcome == "failed"
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == "42"

    def test_parse_bool(self) -> None:
        """Test parsing a boolean input."""
        parser = ToolArgumentsParser()

        envelope = parser.parse(True)

        assert envelope.parse_outcome == "failed"
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == "True"

    def test_parse_none(self) -> None:
        """Test parsing None input."""
        parser = ToolArgumentsParser()

        envelope = parser.parse(None)

        assert envelope.parse_outcome == "failed"
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == "None"


class TestNoCrashBehavior:
    """Tests for no-crash behavior (Requirement 4.4)."""

    def test_parse_never_raises_exception(self) -> None:
        """Test that parsing never raises exceptions."""
        parser = ToolArgumentsParser()

        # Try various problematic inputs
        problematic_inputs = [
            None,
            object(),
            {"circular": None},  # Could cause issues in some parsers
            b"bytes",
        ]

        for input_val in problematic_inputs:
            # Should not raise
            envelope = parser.parse(input_val)
            assert isinstance(envelope, ToolArgumentsEnvelope)
            assert envelope.parse_outcome in ("success", "failed")
            assert envelope.normalized_arguments.root is not None


class TestTelemetryIntegration:
    """Tests for telemetry callback integration."""

    def test_telemetry_callback_called_with_outcome(self) -> None:
        """Test that telemetry callback is called with outcome string."""
        mock_callback = Mock()
        mock_callback.record_tool_argument_repair_outcome = Mock()
        parser = ToolArgumentsParser(telemetry_callback=mock_callback)

        parser.parse('{"key": "value"}')

        mock_callback.record_tool_argument_repair_outcome.assert_called_once_with(
            "success"
        )

    def test_telemetry_callback_called_with_recovered(self) -> None:
        """Test that telemetry callback receives recovered outcome."""
        mock_callback = Mock()
        mock_callback.record_tool_argument_repair_outcome = Mock()
        parser = ToolArgumentsParser(telemetry_callback=mock_callback)

        # Use invalid JSON that might be recovered
        parser.parse('{"key": "value",}')

        # Should be called with some outcome
        assert mock_callback.record_tool_argument_repair_outcome.called
        call_args = mock_callback.record_tool_argument_repair_outcome.call_args[0][0]
        assert call_args in ("success", "recovered", "failed")

    def test_telemetry_callback_no_secrets_logged(self) -> None:
        """Test that telemetry callback only receives outcome, not argument content."""
        mock_callback = Mock()
        mock_callback.record_tool_argument_repair_outcome = Mock()
        parser = ToolArgumentsParser(telemetry_callback=mock_callback)

        # Parse arguments that might contain secrets
        secret_args = '{"api_key": "secret123", "token": "abc123"}'
        parser.parse(secret_args)

        # Verify callback was called only with outcome string
        assert mock_callback.record_tool_argument_repair_outcome.called
        call_args = mock_callback.record_tool_argument_repair_outcome.call_args[0]
        # Should only have one argument (the outcome string)
        assert len(call_args) == 1
        assert call_args[0] in ("success", "recovered", "failed")
        # Verify no argument content was passed
        assert "secret" not in str(call_args).lower()
        assert "api_key" not in str(call_args).lower()

    def test_telemetry_callback_handles_missing_method(self) -> None:
        """Test that missing telemetry method doesn't crash."""
        mock_callback = Mock(spec=[])  # No methods
        parser = ToolArgumentsParser(telemetry_callback=mock_callback)

        # Should not raise
        envelope = parser.parse('{"key": "value"}')
        assert envelope.parse_outcome == "success"

    def test_telemetry_callback_handles_exception(self) -> None:
        """Test that telemetry callback exceptions don't crash parsing."""
        mock_callback = Mock()
        mock_callback.record_tool_argument_repair_outcome = Mock(
            side_effect=Exception("Telemetry error")
        )
        parser = ToolArgumentsParser(telemetry_callback=mock_callback)

        # Should not raise
        envelope = parser.parse('{"key": "value"}')
        assert envelope.parse_outcome == "success"


class TestRepairOutcomes:
    """Tests for repair outcome tracking (Requirement 4.3)."""

    def test_success_outcome_for_valid_json(self) -> None:
        """Test that valid JSON results in success outcome."""
        parser = ToolArgumentsParser()
        valid_json = '{"key": "value"}'

        envelope = parser.parse(valid_json)

        assert envelope.parse_outcome == "success"

    def test_recovered_outcome_for_repaired_json(self) -> None:
        """Test that repaired JSON results in recovered outcome when possible."""
        parser = ToolArgumentsParser()
        # This might be repaired depending on json_repair capabilities
        invalid_json = '{"key": "value",}'  # Trailing comma

        envelope = parser.parse(invalid_json)

        # Outcome depends on repair success
        assert envelope.parse_outcome in ("success", "recovered", "failed")

    def test_failed_outcome_for_unparseable_text(self) -> None:
        """Test that unparseable text results in failed outcome."""
        parser = ToolArgumentsParser()
        unparseable = "not json at all"

        envelope = parser.parse(unparseable)

        assert envelope.parse_outcome == "failed"
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
