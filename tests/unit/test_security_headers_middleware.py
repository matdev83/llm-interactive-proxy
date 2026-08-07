"""
Tests for SecurityHeadersMiddleware.

Verifies that security headers are correctly applied to HTTP responses:
- API responses (JSON) get lightweight headers
- HTML responses (SSO pages) get full security headers including CSP
"""

import pytest
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient
from src.core.app.middleware.security_headers_middleware import (
    API_SECURITY_HEADERS,
    HTML_SECURITY_HEADERS,
    SecurityHeadersMiddleware,
    add_security_headers_middleware,
)


@pytest.fixture
def app_with_middleware() -> FastAPI:
    """Create a test FastAPI app with security headers middleware."""
    app = FastAPI()
    add_security_headers_middleware(app)

    @app.get("/api/test")
    async def api_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/html/test")
    async def html_endpoint() -> HTMLResponse:
        return HTMLResponse(content="<html><body>Test</body></html>")

    @app.get("/json/explicit")
    async def json_explicit() -> JSONResponse:
        return JSONResponse(content={"data": "test"})

    @app.get("/custom-headers")
    async def custom_headers() -> Response:
        """Endpoint that sets its own headers - should not be overwritten."""
        response = JSONResponse(content={"data": "test"})
        response.headers["X-Content-Type-Options"] = "custom-value"
        response.headers["Cache-Control"] = "max-age=3600"
        return response

    return app


@pytest.fixture
def client(app_with_middleware: FastAPI) -> TestClient:
    """Create a test client for the app."""
    return TestClient(app_with_middleware)


class TestAPISecurityHeaders:
    """Tests for API (JSON) response security headers."""

    def test_api_response_has_nosniff_header(self, client: TestClient) -> None:
        """API responses should have X-Content-Type-Options: nosniff."""
        response = client.get("/api/test")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_api_response_has_cache_control(self, client: TestClient) -> None:
        """API responses should have Cache-Control: no-store."""
        response = client.get("/api/test")
        assert response.headers.get("Cache-Control") == "no-store"

    def test_api_response_does_not_have_csp(self, client: TestClient) -> None:
        """API responses should NOT have Content-Security-Policy (overkill for JSON)."""
        response = client.get("/api/test")
        assert "Content-Security-Policy" not in response.headers

    def test_api_response_does_not_have_frame_options(self, client: TestClient) -> None:
        """API responses should NOT have X-Frame-Options (irrelevant for JSON)."""
        response = client.get("/api/test")
        assert "X-Frame-Options" not in response.headers

    def test_explicit_json_response_has_api_headers(self, client: TestClient) -> None:
        """Explicit JSONResponse should get API headers."""
        response = client.get("/json/explicit")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("Cache-Control") == "no-store"


class TestHTMLSecurityHeaders:
    """Tests for HTML response security headers."""

    def test_html_response_has_nosniff_header(self, client: TestClient) -> None:
        """HTML responses should have X-Content-Type-Options: nosniff."""
        response = client.get("/html/test")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_html_response_has_frame_options(self, client: TestClient) -> None:
        """HTML responses should have X-Frame-Options: DENY."""
        response = client.get("/html/test")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_html_response_has_csp(self, client: TestClient) -> None:
        """HTML responses should have Content-Security-Policy."""
        response = client.get("/html/test")
        csp = response.headers.get("Content-Security-Policy")
        assert csp is not None
        # Verify key CSP directives are present
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "script-src" in csp

    def test_html_response_has_hsts(self, client: TestClient) -> None:
        """HTML responses should have Strict-Transport-Security."""
        response = client.get("/html/test")
        hsts = response.headers.get("Strict-Transport-Security")
        assert hsts is not None
        assert "max-age=" in hsts

    def test_html_response_has_referrer_policy(self, client: TestClient) -> None:
        """HTML responses should have Referrer-Policy."""
        response = client.get("/html/test")
        assert (
            response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        )

    def test_html_response_has_xss_protection(self, client: TestClient) -> None:
        """HTML responses should have X-XSS-Protection."""
        response = client.get("/html/test")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"


class TestCustomHeaderPreservation:
    """Tests that custom headers set by handlers are not overwritten."""

    def test_custom_nosniff_preserved(self, client: TestClient) -> None:
        """Custom X-Content-Type-Options should be preserved."""
        response = client.get("/custom-headers")
        assert response.headers.get("X-Content-Type-Options") == "custom-value"

    def test_custom_cache_control_preserved(self, client: TestClient) -> None:
        """Custom Cache-Control should be preserved."""
        response = client.get("/custom-headers")
        assert response.headers.get("Cache-Control") == "max-age=3600"


class TestHeaderConstants:
    """Tests for header constant definitions."""

    def test_api_headers_contain_required_entries(self) -> None:
        """API_SECURITY_HEADERS should contain expected entries."""
        assert "X-Content-Type-Options" in API_SECURITY_HEADERS
        assert "Cache-Control" in API_SECURITY_HEADERS

    def test_html_headers_contain_required_entries(self) -> None:
        """HTML_SECURITY_HEADERS should contain expected entries."""
        required_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Content-Security-Policy",
            "Strict-Transport-Security",
            "Referrer-Policy",
            "X-XSS-Protection",
            "Cache-Control",
        ]
        for header in required_headers:
            assert header in HTML_SECURITY_HEADERS, f"Missing header: {header}"

    def test_html_headers_are_superset_of_api_headers(self) -> None:
        """HTML headers should cover all security concerns that API headers do."""
        # Both should have nosniff
        assert (
            API_SECURITY_HEADERS["X-Content-Type-Options"]
            == HTML_SECURITY_HEADERS["X-Content-Type-Options"]
        )


class TestMiddlewareIntegration:
    """Integration tests for middleware registration."""

    def test_add_security_headers_middleware_rejects_non_fastapi(self) -> None:
        """add_security_headers_middleware should reject non-FastAPI objects."""
        with pytest.raises(TypeError, match="FastAPI instance"):
            add_security_headers_middleware("not a fastapi app")  # type: ignore[arg-type]

    def test_middleware_class_is_callable(self) -> None:
        """SecurityHeadersMiddleware should be callable."""
        middleware = SecurityHeadersMiddleware()
        assert callable(middleware)
