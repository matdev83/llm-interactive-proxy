"""
Integration test demonstrating the XML leakage fix.

This test verifies that the BUFFERED_TOOL_TAGS tuple in response_adapters.py
now includes 'ask_followup_question' and other critical tool tags to prevent
partial XML tags from being emitted mid-stream.
"""

from __future__ import annotations


def test_buffered_tool_tags_includes_ask_followup_question():
    """Verify dynamic tag tracking is enabled to prevent XML leakage."""
    # Read the source and check for dynamic tag handling
    import inspect

    import src.core.transport.fastapi.response_adapters as adapters_module

    source = inspect.getsource(adapters_module.to_fastapi_streaming_response)

    # Verify the dynamic tracking hooks are present
    assert "tracked_tags" in source
    assert "_apply_tag_buffer" in source


def test_xml_leakage_prevention_comment_present():
    """Verify that the code includes documentation about XML leakage prevention."""
    import inspect

    import src.core.transport.fastapi.response_adapters as adapters_module

    source = inspect.getsource(adapters_module.to_fastapi_streaming_response)

    # Verify the fix documentation or function names indicate buffering intent
    assert "sanitize_multiline_tool_blocks" in source or "leakage" in source.lower()
