"""SSRF-oriented URL checks and httpx redirect validation (Hermes-inspired).

Lives at ``src.core.url_safety`` (not ``src.core.security``) to avoid import cycles
with ``src.core.security`` package initialization during SSO / app config load.

DNS rebinding and time-of-check/time-of-use (TOCTOU): ``is_safe_url`` resolves the
hostname (or validates a literal IP) at call time, and ``ssrf_redirect_guard`` runs
when httpx exposes the next redirect URL. A malicious or flaky resolver can still
associate a public hostname with a private address *after* those checks or between
the guard and the actual socket connect, so these helpers reduce SSRF surface area
but do not replace network-level egress controls or a full split-horizon DNS strategy.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import ParseResult, urlparse, urlunparse

logger = logging.getLogger(__name__)

_BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
    }
)

_CGNAT_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")

# RFC 5737 documentation / benchmark ranges — Python 3.10 marks some as ``is_private``,
# but they are not customer VPC addresses; allow so tests and probes can use TEST-NET.
_DOCUMENTATION_NETS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("192.0.2.0/24"),
    ipaddress.IPv4Network("198.51.100.0/24"),
    ipaddress.IPv4Network("203.0.113.0/24"),
)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Block addresses that should never be reached from SSRF guards."""
    if isinstance(ip, ipaddress.IPv4Address):
        for net in _DOCUMENTATION_NETS:
            if ip in net:
                return False
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_unspecified:
        return True
    return isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK


def _netloc_for_safe_log(parsed: ParseResult) -> str:
    host = parsed.hostname or ""
    if not host:
        return ""
    if ":" in host and not host.startswith("["):
        host_bracketed = f"[{host}]"
    else:
        host_bracketed = host
    if parsed.port:
        return f"{host_bracketed}:{parsed.port}"
    return host_bracketed


def is_safe_url(url: str) -> bool:
    """Return True if the URL does not target obviously private/internal addresses."""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return False

        if hostname in _BLOCKED_HOSTNAMES:
            logger.warning("Blocked request to internal hostname: %s", hostname)
            return False

        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None

        if ip is not None:
            if _is_blocked_ip(ip):
                logger.warning(
                    "Blocked request to private/internal address: %s", hostname
                )
                return False
            return True

        try:
            addr_info = socket.getaddrinfo(
                hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
        except OSError:
            logger.warning("Blocked request — DNS resolution failed for: %s", hostname)
            return False

        for _family, _type, _proto, _canon, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                resolved = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if _is_blocked_ip(resolved):
                logger.warning(
                    "Blocked request to private/internal address: %s -> %s",
                    hostname,
                    ip_str,
                )
                return False

        return True

    except Exception as exc:
        logger.warning("Blocked request — URL safety check error for %s: %s", url, exc)
        return False


def safe_url_for_log(url: str, max_len: int = 80) -> str:
    """Return a URL safe for logs: no userinfo, query, or fragment."""
    if max_len <= 0:
        return ""
    try:
        p = urlparse(url)
        netloc = _netloc_for_safe_log(p)
        scheme = p.scheme or "http"
        path = p.path or ""
        safe = urlunparse((scheme, netloc, path, "", "", ""))
    except Exception:
        return ""

    if len(safe) <= max_len:
        return safe
    return f"{safe[: max_len - 3]}..."


async def ssrf_redirect_guard(response: Any) -> None:
    """httpx response hook: reject redirects to private/internal targets."""
    if not getattr(response, "is_redirect", False):
        return
    next_req = getattr(response, "next_request", None)
    if next_req is None:
        return
    redirect_url = str(next_req.url)
    if not is_safe_url(redirect_url):
        raise ValueError(
            "Blocked redirect to private/internal address: "
            f"{safe_url_for_log(redirect_url)}"
        )


def assert_url_safe_for_egress(url: str) -> None:
    """Raise if ``url`` is not suitable for server-side outbound HTTP (SSRF guard).

    Uses the same policy as :func:`is_safe_url`. Intended for preflight checks
    before GET/POST when the URL comes from configuration or OIDC/SAML metadata.
    """
    if is_safe_url(url):
        return
    raise ValueError(
        "URL blocked for egress (unsafe target): " f"{safe_url_for_log(url)}"
    )


def httpx_redirect_follow_kwargs() -> dict[str, Any]:
    """Keyword args for :class:`httpx.AsyncClient` when redirects must be followed safely.

    ``httpx`` defaults ``follow_redirects`` to ``False`` on clients; when callers
    enable redirect following, combine with :func:`ssrf_redirect_guard` so each
    redirect target is checked.
    """
    return {
        "follow_redirects": True,
        "event_hooks": {"response": [ssrf_redirect_guard]},
    }
