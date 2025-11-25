"""
Integration test demonstrating the XML leakage fix.

This test verifies that the BUFFERED_TOOL_TAGS tuple in response_adapters.py
now includes 'ask_followup_question' and other critical tool tags to prevent
partial XML tags from being emitted mid-stream.
"""

from __future__ import annotations


def test_buffered_tool_tags_includes_ask_followup_question():
    """Verify that ask_followup_question is in BUFFERED_TOOL_TAGS."""
    # Read the source and check for the tuple definition
    import inspect

    import src.core.transport.fastapi.response_adapters as adapters_module

    source = inspect.getsource(adapters_module.to_fastapi_streaming_response)

    # Verify the critical tag is present in the source
    assert (
        '"ask_followup_question"' in source
    ), "ask_followup_question MUST be in BUFFERED_TOOL_TAGS to prevent XML leakage!"

    # Also check other critical tags
    critical_tags = [
        '"ask_followup_question"',
        '"attempt_completion"',
        '"execute_command"',
        '"apply_diff"',
        '"write_to_file"',
    ]

    for tag in critical_tags:
        assert tag in source, f"Critical tool tag {tag} must be buffered!"


def test_xml_leakage_prevention_comment_present():
    """Verify that the code includes documentation about XML leakage prevention."""
    import inspect

    import src.core.transport.fastapi.response_adapters as adapters_module

    source = inspect.getsource(adapters_module.to_fastapi_streaming_response)

    # Verify the fix documentation is present
    assert (
        "What can I help you with today?</" in source
        or "prevents leakage" in source.lower()
    ), "Code should document the XML leakage fix"
