from src.connectors.gemini_base.retry_delay_parser import extract_retry_delay
from src.core.common.exceptions import BackendError


def test_extract_retry_delay_uses_retry_after_detail() -> None:
    err = BackendError(
        message="rate limited",
        code="rate_limit_exceeded",
        status_code=429,
        details={"retry_after": 2},
    )

    assert extract_retry_delay(err) == 2.0


def test_extract_retry_delay_uses_retry_after_header() -> None:
    err = BackendError(
        message="rate limited",
        code="rate_limit_exceeded",
        status_code=429,
        details={"headers": {"Retry-After": "1.5"}},
    )

    assert extract_retry_delay(err) == 1.5
