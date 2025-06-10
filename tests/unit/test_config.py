# import os # F401: Removed
from src.core.config import _load_config


def test_collect_single_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test_key_gemini")
    cfg = _load_config()
    assert cfg["gemini_api_keys"] == {"GEMINI_API_KEY": "test_key_gemini"}
    assert "openrouter_api_keys" not in cfg


def test_collect_numbered_openrouter_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "key1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "key2")
    cfg = _load_config()
    assert cfg["openrouter_api_keys"] == {
        "OPENROUTER_API_KEY_1": "key1",
        "OPENROUTER_API_KEY_2": "key2",
    }
    assert "gemini_api_keys" not in cfg


def test_conflicting_key_formats(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "base_key")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "numbered_key")
    cfg = _load_config()
    # Numbered keys should take precedence if base key also exists
    assert cfg["openrouter_api_keys"] == {"OPENROUTER_API_KEY_1": "numbered_key"}


def test_no_api_keys(monkeypatch):
    # Ensure all relevant env vars are cleared
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21): # Max number of keys supported
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    cfg = _load_config()
    assert "gemini_api_keys" not in cfg
    assert "openrouter_api_keys" not in cfg


def test_multiple_gemini_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY_1", "gkey1")
    monkeypatch.setenv("GEMINI_API_KEY_2", "gkey2")
    cfg = _load_config()
    assert cfg["gemini_api_keys"] == {
        "GEMINI_API_KEY_1": "gkey1",
        "GEMINI_API_KEY_2": "gkey2",
    }


def test_mixed_gemini_and_openrouter_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY_1", "gkey1")
    monkeypatch.setenv("OPENROUTER_API_KEY_3", "orkey3")
    cfg = _load_config()
    assert cfg["gemini_api_keys"] == {"GEMINI_API_KEY_1": "gkey1"}
    assert cfg["openrouter_api_keys"] == {"OPENROUTER_API_KEY_3": "orkey3"}


def test_gemini_with_multiple_openrouter_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem_key_single")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "or_key_1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "or_key_2")
    cfg = _load_config()
    assert cfg["gemini_api_keys"] == {"GEMINI_API_KEY": "gem_key_single"}
    assert cfg["openrouter_api_keys"] == {
        "OPENROUTER_API_KEY_1": "or_key_1",
        "OPENROUTER_API_KEY_2": "or_key_2",
    }


def test_openrouter_only(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_key_single")
    cfg = _load_config()
    assert cfg["openrouter_api_keys"] == {"OPENROUTER_API_KEY": "or_key_single"}
    assert "gemini_api_keys" not in cfg


def test_redaction_env(monkeypatch):
    monkeypatch.setenv("REDACT_API_KEYS_IN_PROMPTS", "false")
    cfg = _load_config()
    assert cfg["redact_api_keys_in_prompts"] is False
    monkeypatch.setenv("REDACT_API_KEYS_IN_PROMPTS", "true")
    cfg = _load_config()
    assert cfg["redact_api_keys_in_prompts"] is True


def test_force_set_project_env(monkeypatch):
    monkeypatch.setenv("FORCE_SET_PROJECT", "true")
    cfg = _load_config()
    assert cfg["force_set_project"] is True
    monkeypatch.setenv("FORCE_SET_PROJECT", "false")
    cfg = _load_config()
    assert cfg["force_set_project"] is False
