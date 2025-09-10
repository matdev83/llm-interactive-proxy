from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.services.command_service import get_command_pattern

# --- Tests for get_command_pattern ---


def test_get_command_pattern_default_prefix() -> None:
    pattern = get_command_pattern(DEFAULT_COMMAND_PREFIX)
    assert pattern.match("!/hello")
    assert pattern.match("!/cmd(arg=val)")
    assert not pattern.match("/hello")
    m = pattern.match("!/hello")
    assert m and m.group("cmd") == "hello" and (m.group("args") or "") == ""
    m = pattern.match("!/cmd(arg=val)")
    assert m and m.group("cmd") == "cmd" and m.group("args") == "arg=val"


def test_get_command_pattern_custom_prefix() -> None:
    pattern = get_command_pattern("@")
    assert pattern.match("@hello")
    assert pattern.match("@cmd(arg=val)")
    assert not pattern.match("!/hello")
