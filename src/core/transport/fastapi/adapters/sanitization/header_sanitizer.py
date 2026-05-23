"""Header sanitization for response adapters."""

from __future__ import annotations


class HeaderSanitizer:
    """Filter HTTP headers to allowed set.

    Removes hop-by-hop headers and filters to only allow headers with
    specific prefixes that are safe to forward to clients.
    """

    ALLOWED_PREFIXES: tuple[str, ...] = (
        "x-",
        "access-control-",
        "anthropic-",
        "openai-",
        "zenmux-",
    )
    """Allowed header name prefixes."""

    HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
        {
            "content-encoding",
            "transfer-encoding",
            "content-length",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "upgrade",
        }
    )
    """Hop-by-hop headers to remove per RFC 2616."""

    def sanitize(self, headers: dict[str, str] | None) -> dict[str, str]:
        """Remove disallowed headers.

        Args:
            headers: Headers dictionary or None

        Returns:
            Filtered headers dictionary with only allowed headers
        """
        if headers is None:
            return {}

        filtered: dict[str, str] = {}
        for key, value in headers.items():
            lowercase = key.lower()
            if lowercase in self.HOP_BY_HOP_HEADERS:
                continue
            if any(lowercase.startswith(prefix) for prefix in self.ALLOWED_PREFIXES):
                filtered[key] = value

        return filtered
