import logging
from src.security import APIKeyRedactor


def test_redactor_replaces_keys_and_logs(caplog):
    redactor = APIKeyRedactor(["SECRET"])
    with caplog.at_level(logging.WARNING):
        result = redactor.redact("my SECRET key")
    assert result == "my (API_KEY_HAS_BEEN_REDACTED) key"
    assert any("API key detected" in rec.message for rec in caplog.records)
