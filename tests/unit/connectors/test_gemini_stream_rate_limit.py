from src.connectors.gemini_base.stream_processor import (
    build_rate_limit_backend_error,
)


def test_build_rate_limit_backend_error_handles_quota_payload() -> None:
    payload = {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "You have exhausted your capacity on this model. Your quota will reset after 4s.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "4.0s",
                }
            ],
        }
    }

    err = build_rate_limit_backend_error(payload, model="google/gemini-3-pro-high")

    assert err is not None
    assert err.code == "quota_exceeded"
    assert err.status_code == 429
    assert err.details == payload
    assert "reset after 4s" in err.message


def test_build_rate_limit_backend_error_handles_simple_429() -> None:
    payload = {"error": {"code": 429, "message": ""}}

    err = build_rate_limit_backend_error(payload, model="google/gemini-3-pro-high")

    assert err is not None
    assert err.code == "rate_limit_exceeded"
    assert err.status_code == 429
    assert "rate limiting" in err.message


def test_build_rate_limit_backend_error_ignores_non_rate_limit() -> None:
    payload = {"error": {"code": 403, "message": "forbidden"}}

    err = build_rate_limit_backend_error(payload, model="google/gemini-3-pro-high")

    assert err is None
