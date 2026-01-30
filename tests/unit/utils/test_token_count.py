from __future__ import annotations

import builtins

import pytest


@pytest.fixture(autouse=False)
def disable_tiktoken_import(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def _raise_for_tiktoken(
        name: str,
        globals_: dict | None = None,
        locals_: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "tiktoken":
            raise ModuleNotFoundError("No module named 'tiktoken'")
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raise_for_tiktoken)


def test_count_tokens_returns_zero_for_empty_text_when_tiktoken_missing(
    disable_tiktoken_import: None,
) -> None:
    from src.core.utils.token_count import count_tokens

    assert count_tokens("") == 0


def test_extract_prompt_text_basic():
    from src.core.utils.token_count import extract_prompt_text

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "User prompt"},
    ]
    result = extract_prompt_text(messages)
    assert result == "system: System prompt\nuser: User prompt"


def test_extract_prompt_text_with_tool_calls():
    from src.core.utils.token_count import extract_prompt_text

    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"location": "London"}',
                    }
                }
            ],
        }
    ]
    result = extract_prompt_text(messages)
    assert 'assistant (tool_call): get_weather({"location": "London"})' in result


def test_extract_prompt_text_with_tool_response():
    from src.core.utils.token_count import extract_prompt_text

    messages = [{"role": "tool", "content": "Sunny"}]
    result = extract_prompt_text(messages)
    assert result == "tool: Sunny"

