"""RED-phase tests for URL safety helpers (implementation pending in ``url_safety``)."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest
from src.core.url_safety import (
    assert_url_safe_for_egress,
    httpx_redirect_follow_kwargs,
    is_safe_url,
    safe_url_for_log,
    ssrf_redirect_guard,
)


def test_is_safe_url_rejects_loopback_literal() -> None:
    assert is_safe_url("http://127.0.0.1/") is False


def test_assert_url_safe_for_egress_raises_on_loopback() -> None:
    with pytest.raises(ValueError) as excinfo:
        assert_url_safe_for_egress("http://127.0.0.1/metadata")
    assert safe_url_for_log("http://127.0.0.1/metadata") in str(excinfo.value)


def test_httpx_redirect_follow_kwargs_shape() -> None:
    kwargs = httpx_redirect_follow_kwargs()
    assert kwargs["follow_redirects"] is True
    assert "response" in kwargs["event_hooks"]
    assert kwargs["event_hooks"]["response"] == [ssrf_redirect_guard]


def test_is_safe_url_rejects_link_local_metadata_ip() -> None:
    assert is_safe_url("http://169.254.169.254/latest/meta-data") is False


def test_is_safe_url_rejects_gcp_metadata_hostname_without_dns() -> None:
    assert is_safe_url("http://metadata.google.internal/") is False


def test_is_safe_url_accepts_public_host_when_getaddrinfo_returns_test_net_ip() -> None:
    pytest.importorskip("socket")
    fake_addr = (
        socket.AF_INET,
        socket.SOCK_STREAM,
        0,
        "",
        ("203.0.113.1", 80),
    )
    with patch("socket.getaddrinfo", return_value=[fake_addr]):
        assert is_safe_url("http://example.com/") is True


def test_is_safe_url_fails_closed_when_getaddrinfo_raises_gaierror() -> None:
    with patch(
        "socket.getaddrinfo",
        side_effect=socket.gaierror(1, "Name or service not known"),
    ):
        assert is_safe_url("http://example.com/") is False


def test_safe_url_for_log_minimal_redaction_contract() -> None:
    """Log-safe URLs must not leak credentials or query secrets.

    Minimal contract: userinfo (``user:pass@``) and the query string are removed
    or truncated so typical secrets do not appear verbatim.
    """
    raw = "http://alice:secret@example.com/api?token=supersecret&foo=1"
    logged = safe_url_for_log(raw)
    assert "alice" not in logged
    assert "secret" not in logged
    assert "supersecret" not in logged
    assert "token=" not in logged


@pytest.mark.asyncio
async def test_ssrf_redirect_guard_rejects_loopback_redirect_target() -> None:
    """Hook used with httpx must reject following a redirect to a private URL.

    Exercised in isolation with a stand-in ``Response`` so no outbound HTTP runs.
    """
    resp = MagicMock()
    resp.is_redirect = True
    resp.next_request = MagicMock()
    resp.next_request.url = "http://127.0.0.1/private"

    with pytest.raises(ValueError):
        await ssrf_redirect_guard(resp)
