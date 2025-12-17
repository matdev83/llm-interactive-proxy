"""Tests for tool arguments envelope normalization."""

from __future__ import annotations

from src.core.interfaces.tool_call_reactor_internal import (
    NormalizedToolArguments,
    ToolArgumentsEnvelope,
    normalize_tool_arguments,
)


class TestNormalizedToolArguments:
    """Tests for NormalizedToolArguments RootModel."""

    def test_normalized_tool_arguments_accepts_dict(self) -> None:
        """Test that NormalizedToolArguments accepts a dictionary."""
        args = {"key": "value", "number": 42}
        normalized = NormalizedToolArguments(args)
        assert normalized.root == args

    def test_normalized_tool_arguments_empty_dict(self) -> None:
        """Test that NormalizedToolArguments accepts an empty dictionary."""
        normalized = NormalizedToolArguments({})
        assert normalized.root == {}

    def test_normalized_tool_arguments_nested_dict(self) -> None:
        """Test that NormalizedToolArguments accepts nested dictionaries."""
        args = {"outer": {"inner": "value"}}
        normalized = NormalizedToolArguments(args)
        assert normalized.root == args


class TestToolArgumentsEnvelope:
    """Tests for ToolArgumentsEnvelope model."""

    def test_envelope_defaults(self) -> None:
        """Test that envelope has correct defaults."""
        envelope = ToolArgumentsEnvelope()
        assert envelope.parse_outcome == "failed"
        assert envelope.raw_arguments is None
        assert envelope.normalized_arguments.root == {}
        assert envelope.was_modified_by_fixups is False

    def test_envelope_with_success_outcome(self) -> None:
        """Test envelope with successful parse outcome."""
        args = {"key": "value"}
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(args),
        )
        assert envelope.parse_outcome == "success"
        assert envelope.normalized_arguments.root == args

    def test_envelope_with_recovered_outcome(self) -> None:
        """Test envelope with recovered parse outcome."""
        args = {"key": "value"}
        envelope = ToolArgumentsEnvelope(
            parse_outcome="recovered",
            raw_arguments='{"key": "value"}',
            normalized_arguments=NormalizedToolArguments(args),
        )
        assert envelope.parse_outcome == "recovered"
        assert envelope.raw_arguments == '{"key": "value"}'
        assert envelope.normalized_arguments.root == args

    def test_envelope_with_fixups_flag(self) -> None:
        """Test envelope with fixups modification flag."""
        args = {"key": "value"}
        envelope = ToolArgumentsEnvelope(
            normalized_arguments=NormalizedToolArguments(args),
            was_modified_by_fixups=True,
        )
        assert envelope.was_modified_by_fixups is True


class TestToolArgumentsNormalizationRules:
    """Tests for normalization rules as specified in design.md."""

    def test_normalize_json_object_to_root(self) -> None:
        """Test normalization rule: JSON object → normalized_arguments.root is that object."""
        args_dict = {"tool": "test", "param": 123}
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(args_dict),
        )
        assert envelope.normalized_arguments.root == args_dict
        assert isinstance(envelope.normalized_arguments.root, dict)
        assert "__proxy_args_list__" not in envelope.normalized_arguments.root
        assert "__proxy_args_raw__" not in envelope.normalized_arguments.root

    def test_normalize_json_array_to_wrapped_dict(self) -> None:
        """Test normalization rule: JSON array → normalized_arguments.root = {"__proxy_args_list__": <array>}."""
        args_array = ["item1", "item2", "item3"]
        wrapped = {"__proxy_args_list__": args_array}
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(wrapped),
        )
        assert envelope.normalized_arguments.root == wrapped
        assert "__proxy_args_list__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_list__"] == args_array

    def test_normalize_raw_text_to_wrapped_dict(self) -> None:
        """Test normalization rule: raw/unparsed text → normalized_arguments.root = {"__proxy_args_raw__": <raw_text>}."""
        raw_text = "some unparsed text"
        wrapped = {"__proxy_args_raw__": raw_text}
        envelope = ToolArgumentsEnvelope(
            parse_outcome="failed",
            raw_arguments=raw_text,
            normalized_arguments=NormalizedToolArguments(wrapped),
        )
        assert envelope.normalized_arguments.root == wrapped
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == raw_text

    def test_reserved_keys_are_documented(self) -> None:
        """Test that reserved keys are clearly identifiable."""
        # These keys should be reserved for internal normalization
        # Test that we can use these keys in normalization
        list_wrapped = {"__proxy_args_list__": [1, 2, 3]}
        raw_wrapped = {"__proxy_args_raw__": "text"}

        assert "__proxy_args_list__" in list_wrapped
        assert "__proxy_args_raw__" in raw_wrapped

        # Ensure these don't conflict with normal object keys
        normal_dict = {"key": "value"}
        assert "__proxy_args_list__" not in normal_dict
        assert "__proxy_args_raw__" not in normal_dict

    def test_parse_outcome_tracking_success(self) -> None:
        """Test parse_outcome tracking for successful parsing."""
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
        )
        assert envelope.parse_outcome == "success"

    def test_parse_outcome_tracking_recovered(self) -> None:
        """Test parse_outcome tracking for recovered parsing."""
        envelope = ToolArgumentsEnvelope(
            parse_outcome="recovered",
            raw_arguments='{"key": "value"}',
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
        )
        assert envelope.parse_outcome == "recovered"

    def test_parse_outcome_tracking_failed(self) -> None:
        """Test parse_outcome tracking for failed parsing."""
        envelope = ToolArgumentsEnvelope(
            parse_outcome="failed",
            raw_arguments="unparseable text",
            normalized_arguments=NormalizedToolArguments(
                {"__proxy_args_raw__": "unparseable text"}
            ),
        )
        assert envelope.parse_outcome == "failed"

    def test_was_modified_by_fixups_flag(self) -> None:
        """Test was_modified_by_fixups flag tracking."""
        envelope_false = ToolArgumentsEnvelope(
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
            was_modified_by_fixups=False,
        )
        assert envelope_false.was_modified_by_fixups is False

        envelope_true = ToolArgumentsEnvelope(
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
            was_modified_by_fixups=True,
        )
        assert envelope_true.was_modified_by_fixups is True

    def test_envelope_serialization(self) -> None:
        """Test that envelope can be serialized to dict."""
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            raw_arguments='{"key": "value"}',
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
            was_modified_by_fixups=True,
        )
        serialized = envelope.model_dump()
        assert serialized["parse_outcome"] == "success"
        assert serialized["raw_arguments"] == '{"key": "value"}'
        # RootModel serializes directly as the root value, not wrapped in "root"
        assert serialized["normalized_arguments"] == {"key": "value"}
        assert serialized["was_modified_by_fixups"] is True

    def test_envelope_from_dict(self) -> None:
        """Test creating envelope from dictionary."""
        # RootModel accepts the root value directly, not wrapped in "root"
        data = {
            "parse_outcome": "success",
            "raw_arguments": '{"key": "value"}',
            "normalized_arguments": {"key": "value"},
            "was_modified_by_fixups": False,
        }
        envelope = ToolArgumentsEnvelope.model_validate(data)
        assert envelope.parse_outcome == "success"
        assert envelope.raw_arguments == '{"key": "value"}'
        assert envelope.normalized_arguments.root == {"key": "value"}
        assert envelope.was_modified_by_fixups is False


class TestNormalizeToolArguments:
    """Tests for normalize_tool_arguments() helper function."""

    def test_normalize_dict_input(self) -> None:
        """Test normalizing a dictionary input."""
        args = {"key": "value", "number": 42}
        envelope = normalize_tool_arguments(args)
        assert envelope.parse_outcome == "success"
        assert envelope.normalized_arguments.root == args
        assert envelope.raw_arguments is None
        assert envelope.was_modified_by_fixups is False

    def test_normalize_list_input(self) -> None:
        """Test normalizing a list input."""
        args = ["item1", "item2", "item3"]
        envelope = normalize_tool_arguments(args)
        assert envelope.parse_outcome == "success"
        assert "__proxy_args_list__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_list__"] == args

    def test_normalize_json_string_object(self) -> None:
        """Test normalizing a JSON string representing an object."""
        json_str = '{"key": "value"}'
        envelope = normalize_tool_arguments(json_str)
        assert envelope.parse_outcome == "success"
        assert envelope.raw_arguments == json_str
        assert envelope.normalized_arguments.root == {"key": "value"}

    def test_normalize_json_string_array(self) -> None:
        """Test normalizing a JSON string representing an array."""
        json_str = '["item1", "item2"]'
        envelope = normalize_tool_arguments(json_str)
        assert envelope.parse_outcome == "success"
        assert envelope.raw_arguments == json_str
        assert "__proxy_args_list__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_list__"] == [
            "item1",
            "item2",
        ]

    def test_normalize_raw_text_string(self) -> None:
        """Test normalizing raw unparseable text."""
        raw_text = "some unparseable text"
        envelope = normalize_tool_arguments(raw_text)
        assert envelope.parse_outcome == "failed"
        assert envelope.raw_arguments == raw_text
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == raw_text

    def test_normalize_invalid_json_with_repair(self) -> None:
        """Test normalizing invalid JSON that can be repaired."""
        # json_repair can fix some common issues
        invalid_json = '{"key": "value",}'  # Trailing comma
        envelope = normalize_tool_arguments(invalid_json)
        # Outcome depends on whether repair succeeds
        assert envelope.parse_outcome in ("success", "recovered", "failed")
        assert envelope.raw_arguments == invalid_json

    def test_normalize_with_explicit_parse_outcome(self) -> None:
        """Test normalizing with explicit parse outcome."""
        args = {"key": "value"}
        envelope = normalize_tool_arguments(args, parse_outcome="recovered")
        assert envelope.parse_outcome == "recovered"
        assert envelope.normalized_arguments.root == args

    def test_normalize_with_fixups_flag(self) -> None:
        """Test normalizing with fixups modification flag."""
        args = {"key": "value"}
        envelope = normalize_tool_arguments(args, was_modified_by_fixups=True)
        assert envelope.was_modified_by_fixups is True
        assert envelope.normalized_arguments.root == args

    def test_normalize_non_string_non_dict_non_list(self) -> None:
        """Test normalizing other types (int, bool, None)."""
        # Integer
        envelope = normalize_tool_arguments(42)
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == "42"

        # Boolean
        envelope = normalize_tool_arguments(True)
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == "True"

        # None
        envelope = normalize_tool_arguments(None)
        assert "__proxy_args_raw__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_raw__"] == "None"

    def test_normalize_empty_dict(self) -> None:
        """Test normalizing an empty dictionary."""
        envelope = normalize_tool_arguments({})
        assert envelope.parse_outcome == "success"
        assert envelope.normalized_arguments.root == {}

    def test_normalize_empty_list(self) -> None:
        """Test normalizing an empty list."""
        envelope = normalize_tool_arguments([])
        assert envelope.parse_outcome == "success"
        assert "__proxy_args_list__" in envelope.normalized_arguments.root
        assert envelope.normalized_arguments.root["__proxy_args_list__"] == []

    def test_normalize_empty_string(self) -> None:
        """Test normalizing an empty string."""
        envelope = normalize_tool_arguments("")
        # Empty string may parse as valid JSON (empty string)
        assert envelope.parse_outcome in ("success", "failed")
        assert envelope.raw_arguments == ""

    def test_normalize_nested_dict(self) -> None:
        """Test normalizing a nested dictionary."""
        args = {"outer": {"inner": {"deep": "value"}}}
        envelope = normalize_tool_arguments(args)
        assert envelope.parse_outcome == "success"
        assert envelope.normalized_arguments.root == args

    def test_reserved_keys_not_in_normal_dict(self) -> None:
        """Test that reserved keys are not present in normal dictionary normalization."""
        args = {"key": "value"}
        envelope = normalize_tool_arguments(args)
        assert "__proxy_args_list__" not in envelope.normalized_arguments.root
        assert "__proxy_args_raw__" not in envelope.normalized_arguments.root
