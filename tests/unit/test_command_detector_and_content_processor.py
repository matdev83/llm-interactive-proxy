from __future__ import annotations

from src.core.services.command_content_processor import CommandContentProcessor
from src.core.services.command_detector import CommandDetector


def test_command_detector_detects_command():
    detector = CommandDetector()
    info = detector.detect("Hi !/help() there")
    assert info is not None
    assert info["cmd_name"] == "help"
    assert info["args_str"] is None
    assert isinstance(info["match_start"], int)
    assert isinstance(info["match_end"], int)


def test_content_processor_sanitizes_part():
    processor = CommandContentProcessor()
    assert processor.process_part("Hi !/help() there") == "Hi there"
    assert processor.process_part("!/set(x=1)") == ""
    assert processor.process_part("No command") == "No command"
