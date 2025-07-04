import pytest # Add import
from src.core.config import _load_config


def test_collect_single_gemini_key(monkeypatch):
    # Clean slate for this test
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "test_key_gemini")
    cfg = _load_config()
    assert cfg["gemini_api_keys"] == {"GEMINI_API_KEY": "test_key_gemini"}
    assert not cfg["openrouter_api_keys"]


def test_collect_numbered_openrouter_keys(monkeypatch):
    # Clean slate for this test
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

    monkeypatch.setenv("OPENROUTER_API_KEY_1", "key1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "key2")
    cfg = _load_config()
    assert cfg["openrouter_api_keys"] == {
        "OPENROUTER_API_KEY_1": "key1",
        "OPENROUTER_API_KEY_2": "key2",
    }
    assert not cfg["gemini_api_keys"]


def test_conflicting_key_formats(monkeypatch, caplog):
    # Clean slate for this test
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

    monkeypatch.setenv("OPENROUTER_API_KEY", "base_key")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "numbered_key")
    
    cfg = _load_config()
    
    # Should prioritize numbered keys and issue a warning
    assert cfg["openrouter_api_keys"] == {"OPENROUTER_API_KEY_1": "numbered_key"}
    assert "OPENROUTER_API_KEY" not in cfg["openrouter_api_keys"]
    
    # Check that a warning was logged
    assert "Both OPENROUTER_API_KEY and OPENROUTER_API_KEY_<n> environment variables are set" in caplog.text
    assert "Prioritizing OPENROUTER_API_KEY_<n> and ignoring OPENROUTER_API_KEY" in caplog.text


def test_no_api_keys(monkeypatch):
    # Clean slate: remove keys potentially set by session-scoped fixtures
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

    cfg = _load_config()
    assert not cfg["gemini_api_keys"]
    assert not cfg["openrouter_api_keys"]


def test_multiple_gemini_keys(monkeypatch):
    # Clean slate for this test
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

    monkeypatch.setenv("GEMINI_API_KEY_1", "gkey1")
    monkeypatch.setenv("GEMINI_API_KEY_2", "gkey2")
    cfg = _load_config()
    assert cfg["gemini_api_keys"] == {
        "GEMINI_API_KEY_1": "gkey1",
        "GEMINI_API_KEY_2": "gkey2",
    }
    assert not cfg["openrouter_api_keys"]


def test_mixed_gemini_and_openrouter_keys(monkeypatch):
    # Clean slate for this test
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

    monkeypatch.setenv("GEMINI_API_KEY_1", "gkey1")
    monkeypatch.setenv("OPENROUTER_API_KEY_3", "orkey3")
    cfg = _load_config()
    assert cfg["gemini_api_keys"] == {"GEMINI_API_KEY_1": "gkey1"}
    assert cfg["openrouter_api_keys"] == {"OPENROUTER_API_KEY_3": "orkey3"}


def test_gemini_with_multiple_openrouter_keys(monkeypatch):
    # Clean slate for this test
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

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
    # Clean slate for this specific test's expectations
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False) # Ensure base key is not there if we only want numbered
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False) # Remove numbered keys

    monkeypatch.setenv("OPENROUTER_API_KEY", "or_key_single")
    cfg = _load_config()
    assert cfg["openrouter_api_keys"] == {"OPENROUTER_API_KEY": "or_key_single"}
    assert not cfg["gemini_api_keys"]


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
