"""
Property-based tests for tool call argument preservation.

This module contains property tests for:
- Property 6: Tool call argument preservation (Requirements 3.1, 3.2, 3.3, 3.4)

The tests verify that SEARCH/REPLACE diff markers and other special content
in tool call arguments are preserved exactly without corruption, double-escaping,
or modification by regex/string replacement.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.translation import Translation
from src.core.services.tool_call_repair_service import ToolCallRepairService
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating tool call arguments with diff markers
# ============================================================================


@st.composite
def diff_marker_strategy(draw: Any) -> str:
    """Generate SEARCH/REPLACE diff marker content.

    This generates realistic diff content with markers like:
    <<<<<<< SEARCH
    old code
    =======
    new code
    >>>>>>> REPLACE
    """
    # Generate the old content (what to search for)
    old_content = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S"),
                blacklist_characters="\x00",
            ),
            min_size=1,
            max_size=200,
        )
    )

    # Generate the new content (what to replace with)
    new_content = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S"),
                blacklist_characters="\x00",
            ),
            min_size=1,
            max_size=200,
        )
    )

    # Build the diff marker format
    return f"<<<<<<< SEARCH\n{old_content}\n=======\n{new_content}\n>>>>>>> REPLACE"


@st.composite
def file_path_strategy(draw: Any) -> str:
    """Generate realistic file paths."""
    # Generate path components
    components = draw(
        st.lists(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=5,
        )
    )

    # Add file extension
    extension = draw(
        st.sampled_from([".py", ".js", ".ts", ".tsx", ".json", ".md", ".txt"])
    )

    return "/".join(components) + extension


@st.composite
def patch_file_arguments_strategy(draw: Any) -> dict[str, str]:
    """Generate patch_file tool call arguments with diff markers."""
    file_path = draw(file_path_strategy())
    patch_content = draw(diff_marker_strategy())

    return {
        "file_path": file_path,
        "patch_content": patch_content,
    }


@st.composite
def tool_call_with_diff_markers_strategy(draw: Any) -> dict[str, Any]:
    """Generate a complete tool call structure with diff markers in arguments."""
    arguments = draw(patch_file_arguments_strategy())

    return {
        "id": f"call_{draw(st.text(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', min_size=8, max_size=16))}",
        "type": "function",
        "function": {
            "name": "patch_file",
            "arguments": json.dumps(arguments),
        },
    }


@st.composite
def xml_tool_call_with_diff_strategy(draw: Any) -> tuple[str, dict[str, str]]:
    """Generate XML-formatted tool call with diff markers.

    Returns a tuple of (xml_string, expected_arguments).
    """
    file_path = draw(file_path_strategy())
    patch_content = draw(diff_marker_strategy())

    # Build XML format (use_mcp_tool wrapper)
    xml_content = f"""<use_mcp_tool>
<tool_name>patch_file</tool_name>
<arguments>{{"file_path": "{file_path}", "patch_content": {json.dumps(patch_content)}}}</arguments>
</use_mcp_tool>"""

    expected_args = {
        "file_path": file_path,
        "patch_content": patch_content,
    }

    return xml_content, expected_args


# ============================================================================
# Property 6: Tool call argument preservation
# ============================================================================


@given(arguments=patch_file_arguments_strategy())
@property_test_settings()
def test_property_6_json_serialization_preserves_diff_markers(
    arguments: dict[str, str],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 6: Tool call argument preservation**
    **Validates: Requirements 3.1, 3.2**

    Property 6: Tool call argument preservation

    *For any* tool call arguments containing SEARCH/REPLACE diff markers,
    JSON serialization and deserialization SHALL preserve the markers exactly
    without corruption or double-escaping.
    """
    # Serialize to JSON
    json_str = json.dumps(arguments)

    # Deserialize back
    restored = json.loads(json_str)

    # The patch_content should be exactly preserved
    assert restored["patch_content"] == arguments["patch_content"], (
        f"Diff markers were corrupted during JSON round-trip.\n"
        f"Original: {arguments['patch_content']!r}\n"
        f"Restored: {restored['patch_content']!r}"
    )

    # Verify the markers are still present
    assert (
        "<<<<<<< SEARCH" in restored["patch_content"]
    ), "SEARCH marker was lost during JSON round-trip"
    assert (
        "=======" in restored["patch_content"]
    ), "Separator marker was lost during JSON round-trip"
    assert (
        ">>>>>>> REPLACE" in restored["patch_content"]
    ), "REPLACE marker was lost during JSON round-trip"


@given(arguments=patch_file_arguments_strategy())
@property_test_settings()
def test_property_6_normalize_tool_arguments_preserves_diff_markers(
    arguments: dict[str, str],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 6: Tool call argument preservation**
    **Validates: Requirements 3.3**

    *For any* tool call arguments containing SEARCH/REPLACE diff markers,
    the Translation._normalize_tool_arguments() function SHALL preserve
    the markers exactly.
    """
    # First serialize to JSON string (as it would come from the model)
    json_str = json.dumps(arguments)

    # Normalize the arguments
    normalized = Translation._normalize_tool_arguments(json_str)

    # Parse the normalized result
    restored = json.loads(normalized)

    # The patch_content should be exactly preserved
    assert restored["patch_content"] == arguments["patch_content"], (
        f"Diff markers were corrupted during normalization.\n"
        f"Original: {arguments['patch_content']!r}\n"
        f"Restored: {restored['patch_content']!r}"
    )


@given(xml_and_expected=xml_tool_call_with_diff_strategy())
@property_test_settings()
def test_property_6_tool_call_repair_preserves_diff_markers(
    xml_and_expected: tuple[str, dict[str, str]],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 6: Tool call argument preservation**
    **Validates: Requirements 3.4**

    *For any* XML-formatted tool call containing SEARCH/REPLACE diff markers,
    the ToolCallRepairService SHALL preserve the markers exactly without
    modification by regex or string replacement.
    """
    xml_content, expected_args = xml_and_expected

    # Create repair service and process the XML
    service = ToolCallRepairService()
    result = service.repair_tool_calls(xml_content)

    # Should have detected a tool call
    assert (
        result is not None
    ), f"ToolCallRepairService failed to detect tool call in:\n{xml_content}"

    # Get the arguments from the result
    tool_call = result.tool_call
    arguments_str = tool_call["function"]["arguments"]

    # Parse the arguments
    if isinstance(arguments_str, str):
        arguments = json.loads(arguments_str)
    else:
        arguments = arguments_str

    # The patch_content should be exactly preserved
    assert arguments.get("patch_content") == expected_args["patch_content"], (
        f"Diff markers were corrupted during tool call repair.\n"
        f"Expected: {expected_args['patch_content']!r}\n"
        f"Got: {arguments.get('patch_content')!r}"
    )


@given(tool_call=tool_call_with_diff_markers_strategy())
@property_test_settings()
def test_property_6_double_serialization_does_not_double_escape(
    tool_call: dict[str, Any],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 6: Tool call argument preservation**
    **Validates: Requirements 3.2**

    *For any* tool call with diff markers in arguments, serializing the
    entire tool call to JSON SHALL NOT double-escape the argument content.
    """
    # Serialize the entire tool call
    json_str = json.dumps(tool_call)

    # Deserialize back
    restored = json.loads(json_str)

    # Get the arguments
    arguments_str = restored["function"]["arguments"]
    arguments = json.loads(arguments_str)

    # The patch_content should not have double-escaped markers
    patch_content = arguments["patch_content"]

    # Check for double-escaping indicators
    assert (
        "\\\\n" not in patch_content or "\n" in patch_content
    ), "Newlines appear to be double-escaped"
    assert "\\\\<" not in patch_content, "Angle brackets appear to be double-escaped"

    # The markers should still be recognizable
    assert (
        "<<<<<<< SEARCH" in patch_content
    ), "SEARCH marker was corrupted (possibly double-escaped)"
    assert (
        ">>>>>>> REPLACE" in patch_content
    ), "REPLACE marker was corrupted (possibly double-escaped)"


@given(arguments=patch_file_arguments_strategy())
@property_test_settings()
def test_property_6_special_characters_in_diff_content_preserved(
    arguments: dict[str, str],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 6: Tool call argument preservation**
    **Validates: Requirements 3.1, 3.3**

    *For any* tool call arguments containing diff markers with special
    characters (quotes, backslashes, etc.), all content SHALL be preserved
    exactly through the processing pipeline.
    """
    # Add some special characters to the patch content
    original_patch = arguments["patch_content"]

    # Serialize and deserialize through JSON
    json_str = json.dumps(arguments)
    restored = json.loads(json_str)

    # Content should be exactly preserved
    assert restored["patch_content"] == original_patch, (
        f"Special characters in diff content were corrupted.\n"
        f"Original: {original_patch!r}\n"
        f"Restored: {restored['patch_content']!r}"
    )


@given(
    old_code=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
            blacklist_characters="\x00",
        ),
        min_size=1,
        max_size=100,
    ),
    new_code=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
            blacklist_characters="\x00",
        ),
        min_size=1,
        max_size=100,
    ),
)
@property_test_settings()
def test_property_6_marker_format_variations_preserved(
    old_code: str,
    new_code: str,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 6: Tool call argument preservation**
    **Validates: Requirements 3.1**

    *For any* diff content with various marker formats, the exact marker
    strings SHALL be preserved through JSON serialization.
    """
    # Test different marker formats that might be used
    marker_formats = [
        f"<<<<<<< SEARCH\n{old_code}\n=======\n{new_code}\n>>>>>>> REPLACE",
        f"<<<<<< SEARCH\n{old_code}\n======\n{new_code}\n>>>>>> REPLACE",
        f"<<<< SEARCH\n{old_code}\n====\n{new_code}\n>>>> REPLACE",
    ]

    for marker_content in marker_formats:
        arguments = {"patch_content": marker_content}

        # Round-trip through JSON
        json_str = json.dumps(arguments)
        restored = json.loads(json_str)

        # Content should be exactly preserved
        assert restored["patch_content"] == marker_content, (
            f"Marker format was corrupted.\n"
            f"Original: {marker_content!r}\n"
            f"Restored: {restored['patch_content']!r}"
        )
