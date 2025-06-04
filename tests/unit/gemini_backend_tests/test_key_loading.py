import os
import pytest
from src.gemini_cli import load_gemini_api_keys


def test_single_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AI" + "a" * 30)
    assert load_gemini_api_keys() == ["AI" + "a" * 30]


def test_multiple_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_1", "AI" + "b" * 30)
    monkeypatch.setenv("GEMINI_API_KEY_2", "AI" + "c" * 30)
    assert load_gemini_api_keys() == ["AI" + "b" * 30, "AI" + "c" * 30]


def test_both_single_and_numbered(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AI" + "x" * 30)
    monkeypatch.setenv("GEMINI_API_KEY_1", "AI" + "y" * 30)
    with pytest.raises(ValueError):
        load_gemini_api_keys()


def test_invalid_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "badkey")
    with pytest.raises(ValueError):
        load_gemini_api_keys()


def test_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 3):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    with pytest.raises(ValueError):
        load_gemini_api_keys()
