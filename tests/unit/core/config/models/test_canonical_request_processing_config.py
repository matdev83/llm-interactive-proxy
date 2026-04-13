from src.core.config.models.canonical_request_processing import (
    CanonicalRequestProcessingConfig,
)


def test_canonical_request_processing_defaults_are_safe() -> None:
    config = CanonicalRequestProcessingConfig()

    assert config.empty_stream_recovery_prompt
    assert config.max_empty_stream_retries == 1


def test_empty_stream_retry_limit_rejects_negative_values() -> None:
    try:
        CanonicalRequestProcessingConfig(
            max_empty_stream_retries=-1,
        )
    except ValueError as exc:
        assert "max_empty_stream_retries" in str(exc)
    else:
        raise AssertionError("Expected negative retry limit to be rejected")


def test_empty_stream_retry_limit_rejects_large_values() -> None:
    try:
        CanonicalRequestProcessingConfig(
            max_empty_stream_retries=6,
        )
    except ValueError as exc:
        assert "max_empty_stream_retries" in str(exc)
    else:
        raise AssertionError("Expected oversized retry limit to be rejected")
