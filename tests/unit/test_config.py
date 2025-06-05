import os
import pytest
from src import main as app_main


def test_collect_single_gemini_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "A")
    cfg = app_main._load_config()
    assert cfg["gemini_api_key"] == "A"
    assert cfg["gemini_api_keys"] == {"GEMINI_API_KEY": "A"}


def test_collect_numbered_openrouter_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "K1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "K2")
    cfg = app_main._load_config()
    assert cfg["openrouter_api_key"] == "K1"
    assert cfg["openrouter_api_keys"] == {
        "OPENROUTER_API_KEY_1": "K1",
        "OPENROUTER_API_KEY_2": "K2",
    }


def test_conflicting_key_formats(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "A")
    monkeypatch.setenv("GEMINI_API_KEY_1", "B")
    with pytest.raises(ValueError):
        app_main._load_config()
