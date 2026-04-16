# Outbound URL safety (SSRF guards)

The proxy performs **preflight checks** on selected outbound URLs so obviously unsafe targets (loopback, link-local cloud metadata addresses, private RFC1918 space, CGNAT carrier space, and a small set of blocked hostnames) are rejected **before** a request is sent. When HTTP clients **follow redirects**, each redirect target is re-checked so a public URL cannot bounce into an internal address.

## Where this applies

| Area | What is checked |
|------|------------------|
| **SSO** | JWKS URLs, OpenID Connect discovery URLs, token and userinfo endpoints when derived from metadata, SAML metadata URLs |
| **Model registry** | The configured `model_registry.url` before periodic catalog downloads |
| **Enterprise authorization** | The configured authorization API URL when the client follows redirects |
| **Backend HTTP health checks** | Probe URLs when the health checker follows redirects |

Well-known hardcoded vendor endpoints (for example fixed OAuth token URLs used by a specific connector) are not reconfigured through your YAML in the same way; those paths are documented in code comments.

## What operators should do

- Point SSO and model-registry URLs at **real, routable HTTPS endpoints** you trust. Internal-only URLs may be rejected if they resolve to addresses the proxy treats as non-egress-safe.
- If a legitimate URL fails validation, check DNS and routing: the guard resolves hostnames and inspects resolved addresses.
- For implementation details (shared `httpx` client `trust_env=False`, hook wiring, DNS rebinding limits), see [HTTP client security](../../development_guide/http-client-security.md) and the module docstring on `src/core/url_safety.py`.

## Configuration

There is no dedicated YAML toggle for URL safety itself; behavior is implied by the URLs you configure elsewhere:

- **SSO**: `providers.*.metadata_url`, JWKS, and OIDC discovery URLs (see [SSO Configuration](../sso-configuration.md) and [SSO Security](../sso-security.md)).
- **Model registry**: `model_registry.url` in the main proxy configuration (see [Configuration](../configuration.md)).
- **Enterprise authorization** and **HTTP health probes**: URLs from their respective sections in [Configuration](../configuration.md) and [Backend Health Checks](health-checks.md).

## Usage Examples

- **SSO**: Use publicly reachable HTTPS IdP metadata and token endpoints. A metadata URL that resolves only on an admin laptop’s `hosts` file may fail the preflight because the proxy resolves names from its own network context.
- **Health checks**: If a probe URL redirects, each redirect target is validated the same way as the original URL, so a chain cannot land on loopback or RFC1918 space.

## Use Cases

- **Block metadata exfiltration**: Prevent accidental use of URLs that would fetch SAML or OIDC metadata from cloud instance metadata IP ranges.
- **Safer automation**: CI or staging hosts can still use documentation-style addresses (TEST-NET) where appropriate, while obvious private-space targets are rejected before any HTTP request is issued.

## Related documentation

- [SSO Security](../sso-security.md)
- [Configuration](../configuration.md) (`model_registry.url`)
- [Backend Health Checks](health-checks.md)
