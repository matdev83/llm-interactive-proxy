from src.core.services.request_processor_service import _sanitize_agent_text_block


def test_removes_environment_details_block_and_keeps_task() -> None:
    raw = "<environment_details>noise</environment_details>\n<task>Do the thing</task>"
    sanitized, changed = _sanitize_agent_text_block(raw)
    assert sanitized == "<task>Do the thing</task>"
    assert changed is True


def test_removes_open_and_recently_viewed_files_block() -> None:
    raw = (
        "<open_and_recently_viewed_files>files</open_and_recently_viewed_files>\n"
        "Actual instructions here."
    )
    sanitized, changed = _sanitize_agent_text_block(raw)
    assert sanitized == "Actual instructions here."
    assert changed is True


def test_preserves_additional_data_instructions() -> None:
    raw = "<additional_data>tool specs</additional_data>\n" "<task>Run pytest</task>"
    sanitized, changed = _sanitize_agent_text_block(raw)
    assert sanitized == (
        "<additional_data>tool specs</additional_data>\n<task>Run pytest</task>"
    )
    assert changed is False


def test_collapses_excess_blank_lines() -> None:
    raw = "Line 1\n\n\nLine 2"
    sanitized, changed = _sanitize_agent_text_block(raw)
    assert sanitized == "Line 1\n\nLine 2"
    assert changed is True


def test_returns_original_when_no_wrappers_present() -> None:
    raw = "Plain user text"
    sanitized, changed = _sanitize_agent_text_block(raw)
    assert sanitized == raw
    assert changed is False
