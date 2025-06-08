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


def test_no_api_keys(monkeypatch):
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = app_main._load_config()
    assert cfg["gemini_api_keys"] == {}
    assert cfg["openrouter_api_keys"] == {}
    assert cfg["gemini_api_key"] is None
    assert cfg["openrouter_api_key"] is None


def test_multiple_gemini_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_1", "G1")
    monkeypatch.setenv("GEMINI_API_KEY_2", "G2")
    cfg = app_main._load_config()
    assert cfg["gemini_api_keys"] == {
        "GEMINI_API_KEY_1": "G1",
        "GEMINI_API_KEY_2": "G2",
    }
    assert cfg["gemini_api_key"] == "G1"


def test_mixed_gemini_and_openrouter_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "G")
    monkeypatch.setenv("OPENROUTER_API_KEY", "O")
    cfg = app_main._load_config()
    assert cfg["gemini_api_key"] == "G"
    assert cfg["openrouter_api_key"] == "O"


def test_gemini_with_multiple_openrouter_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "G")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "O1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "O2")
    cfg = app_main._load_config()
    assert cfg["gemini_api_key"] == "G"
    assert list(cfg["openrouter_api_keys"].values()) == ["O1", "O2"]


def test_openrouter_only(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "O")
    cfg = app_main._load_config()
    assert cfg["gemini_api_keys"] == {}
    assert cfg["openrouter_api_key"] == "O"


def test_redaction_env(monkeypatch):
    monkeypatch.setenv("REDACT_API_KEYS_IN_PROMPTS", "false")
    cfg = app_main._load_config()
    assert cfg["redact_api_keys_in_prompts"] is False
    monkeypatch.delenv("REDACT_API_KEYS_IN_PROMPTS", raising=False)


def test_force_set_project_env(monkeypatch):
    monkeypatch.setenv("FORCE_SET_PROJECT", "true")
    cfg = app_main._load_config()
    assert cfg["force_set_project"] is True
    monkeypatch.delenv("FORCE_SET_PROJECT", raising=False)
