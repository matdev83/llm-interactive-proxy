import logging
from typing import Any

from src.security import APIKeyRedactor


def test_redactor_replaces_keys_and_logs(caplog: Any) -> None:
    redactor = APIKeyRedactor(["SECRET"])
    with caplog.at_level(logging.WARNING):
        result = redactor.redact("my SECRET key")
    assert result == "my (API_KEY_HAS_BEEN_REDACTED) key"
    assert any("API key detected" in rec.message for rec in caplog.records)


def test_redactor_prioritizes_longer_keys() -> None:
    short = "sk-short"
    long = f"{short}-extra"
    # Provide keys in order that would previously leak the suffix of the longer key
    redactor = APIKeyRedactor([short, long])

    text = f"My key is {long}"
    result = redactor.redact(text)

    assert result == "My key is (API_KEY_HAS_BEEN_REDACTED)"
    assert short not in result
    assert long not in result
