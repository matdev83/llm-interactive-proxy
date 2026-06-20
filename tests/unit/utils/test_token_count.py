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


def test_count_tokens_uses_model_family_specific_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    import src.core.utils.token_count as token_count_module

    # Save original state
    original_encoding = token_count_module._tiktoken_encoding
    token_count_module._tiktoken_encoding = None
    token_count_module._model_tokenizer_cache.clear()

    # Save original tiktoken from sys.modules if present
    original_tiktoken = sys.modules.get("tiktoken")
    if "tiktoken" in sys.modules:
        del sys.modules["tiktoken"]

    class _Encoding:
        def __init__(self, name: str) -> None:
            self._name = name

        def encode(self, _text: str) -> list[int]:
            if self._name == "o200k_base":
                return [1, 2, 3, 4]
            return [1, 2]

    class _FakeTikToken:
        @staticmethod
        def get_encoding(name: str) -> _Encoding:
            return _Encoding(name)

    original_import = builtins.__import__

    def _import_with_fake_tiktoken(
        name: str,
        globals_: dict | None = None,
        locals_: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "tiktoken":
            return _FakeTikToken
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import_with_fake_tiktoken)

    try:
        high_context_tokens = token_count_module.count_tokens("hello", model="gpt-5.1")
        generic_tokens = token_count_module.count_tokens(
            "hello", model="claude-3-5-sonnet"
        )

        assert high_context_tokens == 4
        assert generic_tokens == 2
    finally:
        # Restore original encoding
        token_count_module._tiktoken_encoding = original_encoding
        token_count_module._model_tokenizer_cache.clear()

        # Restore sys.modules to its original state
        if original_tiktoken is not None:
            sys.modules["tiktoken"] = original_tiktoken
        elif "tiktoken" in sys.modules:
            del sys.modules["tiktoken"]
