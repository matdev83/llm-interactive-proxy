"""Tests for ToolCallExtractor.

Following TDD methodology: tests written before implementation.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.tool_call_extractor_interface import IToolCallExtractor
from src.core.services.tool_call_reactor.extractor import ToolCallExtractor


class TestExtractFromAttribute:
    """Tests for extraction from response.tool_calls attribute (Priority 1)."""

    def test_extract_from_tool_calls_attribute(self) -> None:
        """Test extraction from direct tool_calls attribute."""
        extractor = ToolCallExtractor()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        response = Mock()
        response.tool_calls = [tool_call]

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == tool_call

    def test_extract_from_tool_calls_attribute_multiple(self) -> None:
        """Test extraction of multiple tool calls from attribute."""
        extractor = ToolCallExtractor()
        tool_call1 = {"id": "call_1", "function": {"name": "tool1", "arguments": "{}"}}
        tool_call2 = {"id": "call_2", "function": {"name": "tool2", "arguments": "{}"}}
        response = Mock()
        response.tool_calls = [tool_call1, tool_call2]

        result = extractor.extract(response)

        assert len(result) == 2
        assert result[0] == tool_call1
        assert result[1] == tool_call2

    def test_extract_from_tool_calls_attribute_empty_list(self) -> None:
        """Test that empty tool_calls list returns empty result."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_tool_calls_attribute_none(self) -> None:
        """Test that None tool_calls attribute is skipped."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = None

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_tool_calls_attribute_not_list(self) -> None:
        """Test that non-list tool_calls attribute is skipped."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = "not a list"

        result = extractor.extract(response)

        assert result == []


class TestExtractFromMetadata:
    """Tests for extraction from response.metadata.tool_calls (Priority 2)."""

    def test_extract_from_metadata_when_attribute_empty(self) -> None:
        """Test extraction from metadata when tool_calls attribute is empty."""
        extractor = ToolCallExtractor()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        response = Mock()
        response.tool_calls = []
        response.metadata = {"tool_calls": [tool_call]}

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == tool_call

    def test_extract_from_metadata_when_attribute_missing(self) -> None:
        """Test extraction from metadata when tool_calls attribute is missing."""
        extractor = ToolCallExtractor()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        response = Mock()
        del response.tool_calls
        response.metadata = {"tool_calls": [tool_call]}

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == tool_call

    def test_extract_from_metadata_multiple_calls(self) -> None:
        """Test extraction of multiple tool calls from metadata."""
        extractor = ToolCallExtractor()
        tool_call1 = {"id": "call_1", "function": {"name": "tool1", "arguments": "{}"}}
        tool_call2 = {"id": "call_2", "function": {"name": "tool2", "arguments": "{}"}}
        response = Mock()
        response.tool_calls = []
        response.metadata = {"tool_calls": [tool_call1, tool_call2]}

        result = extractor.extract(response)

        assert len(result) == 2
        assert result[0] == tool_call1
        assert result[1] == tool_call2

    def test_extract_from_metadata_empty_list(self) -> None:
        """Test that empty metadata tool_calls list continues to content extraction."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {"tool_calls": []}
        response.content = None

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_metadata_not_list(self) -> None:
        """Test that non-list metadata tool_calls is skipped."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {"tool_calls": "not a list"}
        response.content = None

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_metadata_missing_metadata(self) -> None:
        """Test that missing metadata attribute continues to content extraction."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        del response.metadata
        response.content = None

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_metadata_exception_handling(self) -> None:
        """Test that exceptions accessing metadata are handled gracefully."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = Mock(side_effect=AttributeError("test error"))
        response.content = None

        result = extractor.extract(response)

        assert result == []


class TestExtractFromContent:
    """Tests for extraction from response.content (Priority 3)."""

    def test_extract_from_content_json_string_with_choices(self) -> None:
        """Test extraction from content JSON string with choices structure."""
        extractor = ToolCallExtractor()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        content_dict = {"choices": [{"message": {"tool_calls": [tool_call]}}]}
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = json.dumps(content_dict)

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == tool_call

    def test_extract_from_content_dict_with_choices(self) -> None:
        """Test extraction from content dict with choices structure."""
        extractor = ToolCallExtractor()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        content_dict = {"choices": [{"message": {"tool_calls": [tool_call]}}]}
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = content_dict

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == tool_call

    def test_extract_from_content_list_of_tool_calls(self) -> None:
        """Test extraction from content as direct list of tool calls."""
        extractor = ToolCallExtractor()
        tool_call1 = {"id": "call_1", "function": {"name": "tool1", "arguments": "{}"}}
        tool_call2 = {"id": "call_2", "function": {"name": "tool2", "arguments": "{}"}}
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = [tool_call1, tool_call2]

        result = extractor.extract(response)

        assert len(result) == 2
        assert result[0] == tool_call1
        assert result[1] == tool_call2

    def test_extract_from_content_json_string_list(self) -> None:
        """Test extraction from content JSON string as list."""
        extractor = ToolCallExtractor()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = json.dumps([tool_call])

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == tool_call

    def test_extract_from_content_invalid_json(self) -> None:
        """Test that invalid JSON content returns empty list."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = "not valid json {"

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_content_empty_string(self) -> None:
        """Test that empty content string returns empty list."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = ""

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_content_none(self) -> None:
        """Test that None content returns empty list."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = None

        result = extractor.extract(response)

        assert result == []

    def test_extract_from_content_unexpected_type(self) -> None:
        """Test that unexpected content types return empty list."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = 12345  # Not a string, dict, or list

        result = extractor.extract(response)

        assert result == []


class TestPriorityOrdering:
    """Tests for priority ordering (attribute > metadata > content)."""

    def test_attribute_takes_priority_over_metadata(self) -> None:
        """Test that tool_calls attribute takes priority over metadata."""
        extractor = ToolCallExtractor()
        attr_call = {
            "id": "attr_call",
            "function": {"name": "attr_tool", "arguments": "{}"},
        }
        meta_call = {
            "id": "meta_call",
            "function": {"name": "meta_tool", "arguments": "{}"},
        }
        response = Mock()
        response.tool_calls = [attr_call]
        response.metadata = {"tool_calls": [meta_call]}

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == attr_call

    def test_metadata_takes_priority_over_content(self) -> None:
        """Test that metadata takes priority over content."""
        extractor = ToolCallExtractor()
        meta_call = {
            "id": "meta_call",
            "function": {"name": "meta_tool", "arguments": "{}"},
        }
        content_call = {
            "id": "content_call",
            "function": {"name": "content_tool", "arguments": "{}"},
        }
        content_dict = {"choices": [{"message": {"tool_calls": [content_call]}}]}
        response = Mock()
        response.tool_calls = []
        response.metadata = {"tool_calls": [meta_call]}
        response.content = json.dumps(content_dict)

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == meta_call

    def test_content_used_when_attribute_and_metadata_empty(self) -> None:
        """Test that content is used when attribute and metadata are empty."""
        extractor = ToolCallExtractor()
        content_call = {
            "id": "content_call",
            "function": {"name": "content_tool", "arguments": "{}"},
        }
        content_dict = {"choices": [{"message": {"tool_calls": [content_call]}}]}
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = json.dumps(content_dict)

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == content_call


class TestFailOpenBehavior:
    """Tests for fail-open behavior (exceptions don't crash)."""

    def test_exception_in_attribute_access(self) -> None:
        """Test that exceptions accessing tool_calls attribute are handled."""
        extractor = ToolCallExtractor()
        response = Mock()
        type(response).tool_calls = property(
            lambda self: (_ for _ in ()).throw(ValueError("test"))
        )

        result = extractor.extract(response)

        assert result == []

    def test_exception_in_content_parsing(self) -> None:
        """Test that exceptions during content parsing are handled."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = Mock(side_effect=Exception("parsing error"))

        result = extractor.extract(response)

        assert result == []


class TestEmptyResponse:
    """Tests for empty responses (no tool calls)."""

    def test_no_tool_calls_anywhere(self) -> None:
        """Test that response with no tool calls returns empty list."""
        extractor = ToolCallExtractor()
        response = Mock()
        response.tool_calls = []
        response.metadata = {}
        response.content = None

        result = extractor.extract(response)

        assert result == []

    def test_processed_response_object(self) -> None:
        """Test extraction from ProcessedResponse object."""
        extractor = ToolCallExtractor()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        response = ProcessedResponse(content="", metadata={"tool_calls": [tool_call]})

        result = extractor.extract(response)

        assert len(result) == 1
        assert result[0] == tool_call


class TestInterfaceCompliance:
    """Tests for interface compliance."""

    def test_implements_interface(self) -> None:
        """Test that ToolCallExtractor implements IToolCallExtractor."""
        extractor = ToolCallExtractor()
        assert isinstance(extractor, IToolCallExtractor)
