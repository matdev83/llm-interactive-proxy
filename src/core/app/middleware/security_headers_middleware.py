"""
Security Headers Middleware.

Adds HTTP security headers to all responses to protect against common web attacks.

For API responses (JSON):
- Lightweight headers that don't impact API clients but provide defense in depth

For HTML responses (SSO login pages):
- Full security header suite including CSP to protect browser-based users
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import Request, Response

if TYPE_CHECKING:
    from fastapi import FastAPI

# Low-overhead headers for API responses (JSON)
# These are harmless for API clients and provide basic defense in depth
API_SECURITY_HEADERS: dict[str, str] = {
    # Prevent browsers from MIME-sniffing the response away from declared content-type
    "X-Content-Type-Options": "nosniff",
    # Prevent caching of API responses (security + freshness)
    "Cache-Control": "no-store",
}

# Full security headers for HTML responses (SSO pages)
# These protect browser-based users from XSS, clickjacking, and other attacks
HTML_SECURITY_HEADERS: dict[str, str] = {
    # Prevent browsers from MIME-sniffing
    "X-Content-Type-Options": "nosniff",
    # Prevent clickjacking by disallowing framing
    "X-Frame-Options": "DENY",
    # Enable XSS filter in older browsers (modern browsers have this built-in)
    "X-XSS-Protection": "1; mode=block",
    # Prevent caching of auth pages
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    # Tell browser to always use HTTPS for this domain (1 year)
    # Only effective if served over HTTPS, harmless otherwise
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    # Control referrer information leakage
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Content Security Policy - strict policy for login pages
    # - default-src 'self': Only allow resources from same origin
    # - script-src 'self' 'unsafe-inline': Allow inline scripts (needed for Turnstile and form handling)
    # - style-src 'self' 'unsafe-inline': Allow inline styles (needed for page styling)
    # - img-src 'self' data:: Allow images from same origin and data URIs
    # - connect-src 'self' https://challenges.cloudflare.com: Allow Turnstile verification
    # - frame-src https://challenges.cloudflare.com: Allow Turnstile iframe
    # - frame-ancestors 'none': Prevent this page from being embedded in frames
    # - form-action 'self': Only allow form submissions to same origin
    # - base-uri 'self': Prevent base tag hijacking
    # - object-src 'none': Prevent Flash/Java plugin abuse
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self' https://challenges.cloudflare.com; "
        "frame-src https://challenges.cloudflare.com; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "object-src 'none'"
    ),
}


def _is_html_response(response: Response) -> bool:
    """Check if the response is an HTML response based on content-type header."""
    content_type = response.headers.get("content-type", "")
    return "text/html" in content_type.lower()


class SecurityHeadersMiddleware:
    """
    Middleware that adds security headers to HTTP responses.

    Applies different header sets based on response type:
    - HTML responses get full security headers (CSP, X-Frame-Options, etc.)
    - API responses get lightweight headers (X-Content-Type-Options, Cache-Control)
    """

    async def __call__(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process a request and add security headers to the response.

        Args:
            request: The incoming request
            call_next: The next middleware or endpoint handler

        Returns:
            The response with security headers added
        """
        response = await call_next(request)

        # Determine which header set to apply based on response content type
        if _is_html_response(response):
            headers_to_add = HTML_SECURITY_HEADERS
        else:
            headers_to_add = API_SECURITY_HEADERS

        # Add security headers (don't override if already set by the handler)
        for header_name, header_value in headers_to_add.items():
            if header_name not in response.headers:
                response.headers[header_name] = header_value

        return response


def add_security_headers_middleware(app: "FastAPI") -> None:  # noqa: F821
    """
    Add security headers middleware to a FastAPI application.

    This is a convenience function to add the security headers middleware to an app.

    Args:
        app: The FastAPI application
    """
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    middleware = SecurityHeadersMiddleware()
    app.middleware("http")(middleware.__call__)
