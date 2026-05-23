## 2024-05-23 - Prevent Timing Attacks in Token Validation
**Vulnerability:** API key and token validation in `AuthMiddleware` and `APIKeyMiddleware` used standard Python string equality (`!=`) and set membership (`in`) checks, which leak comparison time and could allow attackers to guess tokens via timing attacks.
**Learning:** Security middleware in Python must always use constant-time comparisons for secrets, especially in custom ASGI/FastAPI middleware that might bypass standard framework-level protections. Standard string comparison is susceptible to timing side channels.
**Prevention:** Always use `secrets.compare_digest(a, b)` when validating authentication tokens, API keys, passwords, or other secrets. Ensure inputs are strings and not `None` before comparing to avoid `TypeError`.
