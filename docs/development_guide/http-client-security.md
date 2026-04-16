# HTTP client security

This note summarizes expectations for outbound HTTP from the proxy: avoid ambient
trust, constrain redirects, and validate URLs that come from configuration before use.

## Shared `httpx.AsyncClient` and `trust_env=False`

The application registers a shared async HTTP client during infrastructure startup
with **`trust_env=False`** so proxy auto-detection from environment variables (HTTP
proxies, `NO_PROXY`, `SSL_CERT_FILE`, etc.) does not silently change routing or TLS
for backend traffic. See `src/core/app/stages/infrastructure.py` (`_register_http_client`).

Other long-lived or validation-scoped clients (for example
`ValidationHttpClientManager` in `src/core/services/validation_http_client_manager.py`
and connector transports) follow the same pattern where outbound behavior must be
explicit and predictable.

## Redirects and `ssrf_redirect_guard`

If you create an `httpx.AsyncClient` (or a one-off request) with
**`follow_redirects=True`**, attach the response hook **`ssrf_redirect_guard`** from
`src.core.url_safety` so each redirect target is checked before the client follows it.
Example (enterprise authorization API client in
`src/core/auth/sso/authorization_service.py`):

```python
async with httpx.AsyncClient(
    timeout=self.config.api_timeout,
    follow_redirects=True,
    event_hooks={"response": [ssrf_redirect_guard]},
) as client:
    response = await client.post(self.config.api_url, json=payload)
```

The health checker uses the same hook when following redirects; see
`src/core/services/health/http_checker.py`.

## Preflight for config-driven URLs

Before issuing a request to a URL supplied by configuration (SSO, health checks,
webhooks, etc.), validate it with **`is_safe_url`** from `src.core.url_safety` so
obviously private, loopback, link-local, and similar targets are rejected early.

For a consistent hard failure, use **`assert_url_safe_for_egress(url)`**, which raises
`ValueError` with a log-safe URL fragment on failure (see `src/core/url_safety.py`).
This is used for model-catalog downloads and SSO metadata flows.

When you intentionally follow redirects, build the client with
**`httpx_redirect_follow_kwargs()`** from the same module so **`follow_redirects=True`**
and **`ssrf_redirect_guard`** are applied together.

These checks complement but do not replace TLS verification, allowlists, and
network-level egress policy. See the module docstring on `src/core/url_safety.py` for
limits (DNS rebinding / TOCTOU).
