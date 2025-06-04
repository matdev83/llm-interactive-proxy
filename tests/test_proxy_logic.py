import pytest

from proxy_logic import process_commands_in_messages, proxy_state
from models import ChatMessage


def teardown_function(function):
    # Reset proxy state after each test
    proxy_state.unset_override_model()


def test_only_set_command_removes_message():
    messages = [ChatMessage(role="user", content="!/set(model=foo)")]
    processed, flag = process_commands_in_messages(messages)
    assert processed == []
    assert flag is True


def test_normal_message_unchanged():
    messages = [ChatMessage(role="user", content="Hello")]
    processed, flag = process_commands_in_messages(messages)
    assert processed == messages
    assert flag is False
