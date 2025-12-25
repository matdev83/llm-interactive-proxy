"""
SSO Service for authentication.

This module handles OAuth2 and SAML authentication flows using Authlib.
"""

import base64
import logging
import time
import uuid
import xml.etree.ElementTree as ET  # noqa: N817
import zlib
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore
from authlib.jose import JsonWebKey, JsonWebToken  # type: ignore
from authlib.jose.errors import DecodeError, JoseError  # type: ignore

from src.core.auth.sso.config import ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import AuthenticationError, ConfigurationError
from src.core.auth.sso.models import JWK, JWKS, SAMLMetadata, SSOResult

logger = logging.getLogger(__name__)

# Maximum number of SAML metadata cache entries to prevent unbounded memory growth.
# 100 entries is sufficient for most deployments (typically 1-10 providers).
# Each entry is roughly 1-5 KB, so 100 entries = ~100-500 KB total.
MAX_SAML_METADATA_CACHE_SIZE = 100


def safe_xml_parse(xml_data: str | bytes) -> ET.Element:
    """
    Safely parse XML data with protection against DoS attacks.

    Protects against:
    - XML bomb attacks (Billion Laughs) - exponential entity expansion
    - Deeply nested XML - stack overflow
    - Large XML content - memory exhaustion

    Args:
        xml_data: XML string or bytes to parse

    Returns:
        Parsed XML element

    Raises:
        AuthenticationError: If XML is unsafe or malformed
    """
    # Import sys inside function to avoid circular import issues
    import sys

    # Convert bytes to string if needed
    if isinstance(xml_data, bytes):
        try:
            xml_str = xml_data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AuthenticationError(
                f"XML data contains invalid UTF-8: {e!s}",
                details={"error": "invalid_encoding"},
                original_error=e,
            ) from e
    else:
        xml_str = xml_data

    # Check size limits (prevent memory exhaustion)
    MAX_XML_SIZE = 10 * 1024 * 1024  # 10MB
    if len(xml_str) > MAX_XML_SIZE:
        raise AuthenticationError(
            f"XML data too large: {len(xml_str)} bytes (limit: {MAX_XML_SIZE} bytes)",
            details={
                "error": "xml_too_large",
                "actual_size": len(xml_str),
                "max_size": MAX_XML_SIZE,
            },
        )

    # Check for XML bomb patterns (entity expansion attacks)
    if "<!DOCTYPE" in xml_str and ("<!ENTITY" in xml_str):
        # Look for entity expansion patterns typical in XML bombs
        import re

        entity_pattern = r'<!ENTITY\s+\w+\s+"&\w+;'
        if re.search(entity_pattern, xml_str, re.IGNORECASE):
            raise AuthenticationError(
                "XML contains potentially malicious entity expansion",
                details={"error": "xml_entity_expansion"},
            )

    # Limit nesting depth to prevent stack overflow
    max_depth = 100

    # Count nested tags to estimate depth
    open_tags = 0
    for char in xml_str:
        if char == "<":
            open_tags += 1
            if open_tags > max_depth:
                raise AuthenticationError(
                    f"XML nesting depth exceeds limit: {open_tags} (limit: {max_depth})",
                    details={
                        "error": "xml_depth_exceeded",
                        "actual_depth": open_tags,
                        "max_depth": max_depth,
                    },
                )

    # Parse with safety measures
    try:
        original_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(min(max_depth * 2, original_limit))

        try:
            # Create safe parser (basic XMLParser without external entity support)
            parser = ET.XMLParser()

            root = ET.fromstring(xml_str, parser)
            return root

        finally:
            sys.setrecursionlimit(original_limit)

    except ET.ParseError as e:
        raise AuthenticationError(
            f"XML parsing failed: {e!s}",
            details={"error": "xml_parse_error", "parse_error": str(e)},
            original_error=e,
        ) from e
    except RecursionError as e:
        raise AuthenticationError(
            "XML nesting depth caused stack overflow",
            details={"error": "xml_stack_overflow"},
            original_error=e,
        ) from e
    except Exception as e:
        raise AuthenticationError(
            f"Unexpected error parsing XML: {e!s}",
            details={"error": "xml_unexpected_error"},
            original_error=e,
        ) from e


class JWKSCache:
    """
    Cache for JSON Web Key Sets (JWKS) from identity providers.

    Caches JWKS for each provider to avoid fetching on every request.
    Keys are automatically refreshed after TTL expires.
    Uses LRU eviction to prevent unbounded memory growth.
    """

    DEFAULT_TTL = 3600  # 1 hour
    DEFAULT_MAX_SIZE = 1000  # Maximum number of cached JWKS entries

    def __init__(self, ttl: int = DEFAULT_TTL, max_size: int = DEFAULT_MAX_SIZE):
        """
        Initialize JWKS cache.

        Args:
            ttl: Time-to-live for cached keys in seconds (default: 1 hour)
            max_size: Maximum number of cached entries (default: 1000)
        """
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._ttl = ttl
        self._max_size = max_size

    def get(self, jwks_uri: str) -> JWKS | None:
        """
        Get cached JWKS for a URI.

        Args:
            jwks_uri: The JWKS endpoint URI

        Returns:
            Cached JWKS data or None if not cached or expired
        """
        entry = self._cache.get(jwks_uri)
        if entry is None:
            return None

        if time.time() > entry.get("expires_at", 0):
            # Expired
            del self._cache[jwks_uri]
            return None

        # Move to end for LRU eviction
        self._cache.move_to_end(jwks_uri)
        return entry.get("jwks")

    def set(self, jwks_uri: str, jwks: JWKS) -> None:
        """
        Cache JWKS for a URI.

        Args:
            jwks_uri: The JWKS endpoint URI
            jwks: The JWKS data to cache
        """
        # Remove existing entry if present (will be re-added at end)
        if jwks_uri in self._cache:
            del self._cache[jwks_uri]

        # Add new entry at end (most recently used)
        self._cache[jwks_uri] = {
            "jwks": jwks,
            "expires_at": time.time() + self._ttl,
        }

        # Enforce size limit using LRU eviction
        while len(self._cache) > self._max_size:
            oldest_uri, _ = self._cache.popitem(last=False)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Evicted JWKS cache entry for %s (max_size=%d reached)",
                    oldest_uri,
                    self._max_size,
                )

    def clear(self) -> None:
        """Clear all cached JWKS."""
        self._cache.clear()


class SSOService:
    """
    Manages SSO authentication with identity providers.

    Handles:
    - OAuth2 client creation and URL generation
    - OAuth2 callback processing and token exchange
    - User identity extraction from ID tokens and userinfo endpoints
    - ID token signature verification using JWKS

    KNOWN LIMITATION - Configuration Hot Reload (Requirement 13.5):

    This service does not support runtime configuration reloading. Provider
    configurations are loaded once at initialization and cached. To apply
    configuration changes (add/remove providers, change credentials, etc.),
    the proxy server must be restarted.

    Rationale:
    - SSO services maintain stateful connections (JWKS cache, OAuth clients)
    - Safe hot-reload requires complex state management and cleanup
    - Configuration changes are infrequent in production environments
    - Server restart is an acceptable operational pattern

    Future Enhancement:
    If hot-reload becomes a requirement, implement via:
    - Admin endpoint: POST /admin/sso/reload
    - Reload sequence: validate config -> clear caches -> reinitialize services
    - Graceful handling of in-flight authentication requests
    """

    def __init__(self, config: SSOConfig, jwks_cache: JWKSCache | None = None):
        """
        Initialize SSO service.

        Args:
            config: SSO configuration
            jwks_cache: Optional JWKS cache (creates new one if not provided)
        """
        self.config = config
        self._jwt = JsonWebToken(["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"])
        self._jwks_cache = jwks_cache or JWKSCache(max_size=JWKSCache.DEFAULT_MAX_SIZE)
        # Use OrderedDict for LRU eviction to prevent unbounded memory growth
        self._saml_metadata_cache: OrderedDict[str, SAMLMetadata] = OrderedDict()

    def get_supported_providers(self) -> list[str]:
        """
        Return list of configured identity providers.

        Returns:
            List of provider names
        """
        return list(self.config.providers.keys())

    def get_enabled_providers(self) -> list[str]:
        """
        Return list of enabled and configured identity providers.

        A provider is included if:
        - It has valid configuration (client_id, client_secret, discovery_url or authorize_url)
        - It is not explicitly disabled (enabled: false)

        Returns:
            List of enabled provider names
        """
        enabled = []
        for name, _config in self.config.providers.items():
            if self.is_provider_enabled(name):
                enabled.append(name)
        return enabled

    def is_provider_enabled(self, provider: str) -> bool:
        """
        Check if a specific provider is enabled and configured.

        A provider is considered enabled if:
        1. It exists in the configuration
        2. It has the enabled flag set to True (or not set, defaulting to True)
        3. It has valid configuration (client_id, client_secret)
        4. It has either discovery_url (OIDC) or authorize_url (manual OAuth2)

        Args:
            provider: Provider name

        Returns:
            True if provider is enabled and configured, False otherwise
        """
        if provider not in self.config.providers:
            return False

        config = self.config.providers[provider]

        # Check if explicitly disabled
        if not config.enabled:
            return False

        # Check if has required credentials
        if not config.client_id or not config.client_secret:
            return False

        # Check if has endpoint configuration
        if config.type == "oauth2":
            # OAuth2 requires either discovery_url or authorize_url
            if not config.discovery_url and not config.authorize_url:
                return False
        elif config.type == "saml" and not config.metadata_url:
            # SAML requires metadata_url
            return False

        return True

    def _get_provider_config(self, provider: str) -> ProviderConfig:
        """
        Get provider configuration or raise error.

        Args:
            provider: Provider name

        Returns:
            Provider configuration

        Raises:
            ConfigurationError: If provider not configured
        """
        if provider not in self.config.providers:
            raise ConfigurationError(f"Provider '{provider}' not configured")
        return self.config.providers[provider]

    async def _fetch_jwks(self, jwks_uri: str) -> JWKS:
        """
        Fetch JWKS from the provider's jwks_uri endpoint.

        Uses caching to avoid fetching on every request.

        Args:
            jwks_uri: The JWKS endpoint URI

        Returns:
            JWKS data containing public keys

        Raises:
            AuthenticationError: If JWKS cannot be fetched
        """
        # Check cache first
        cached = self._jwks_cache.get(jwks_uri)
        if cached is not None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Using cached JWKS for %s", jwks_uri)
            return cached

        # Fetch fresh JWKS
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Fetching JWKS from %s", jwks_uri)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(jwks_uri)
                resp.raise_for_status()
                data = resp.json()

                # Convert to JWKS model
                keys = []
                for k in data.get("keys", []):
                    keys.append(JWK(**k))
                jwks = JWKS(keys=keys)

            # Cache the result
            self._jwks_cache.set(jwks_uri, jwks)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Cached JWKS with %d keys", len(jwks.keys))
            return jwks

        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Failed to fetch JWKS from %s: %s", jwks_uri, e)
            raise AuthenticationError(
                f"Failed to fetch JWKS: {e!s}",
                details={"jwks_uri": jwks_uri, "error": str(e)},
                original_error=e,
            ) from e

    async def _verify_id_token(
        self,
        id_token: str,
        jwks_uri: str | None,
        client_id: str,
        issuer: str | None = None,
    ) -> dict[str, Any]:
        """
        Verify and decode an ID token using JWKS.

        Performs signature verification using the provider's public keys.
        Falls back to unverified decoding if JWKS is unavailable.

        Args:
            id_token: The JWT ID token to verify
            jwks_uri: URI to fetch JWKS from (None to skip verification)
            client_id: Expected audience (client_id)
            issuer: Expected issuer (optional)

        Returns:
            Decoded claims from the ID token

        Raises:
            AuthenticationError: If token verification fails
        """
        if not jwks_uri:
            # Feature: sso-authentication, Property 3: Strict token verification
            # Requirement 11.4: Validate all tokens according to protocol specifications
            #
            # SECURITY: No JWKS URI means we cannot verify the token signature.
            # This violates Requirement 11.4 which mandates token validation.
            #
            # Options:
            # 1. FAIL (recommended): Reject tokens without JWKS verification
            # 2. ALLOW with explicit opt-in: Require allow_unverified_tokens=True in config
            #
            # We enforce FAIL by default for security.
            logger.error(
                "JWKS URI is required for ID token verification. "
                "Cannot verify token signature without JWKS endpoint."
            )
            raise AuthenticationError(
                "ID token verification requires JWKS URI. "
                "Provider configuration must include a valid discovery_url or jwks_uri. "
                "Unverified tokens are rejected for security compliance (Requirement 11.4).",
                details={"jwks_uri": None, "provider": "unknown"},
            )

        # Fetch JWKS and verify signature
        try:
            jwks_model = await self._fetch_jwks(jwks_uri)

            # Import the JWKS as a key set
            # Handle both dataclass and dict (for testing compatibility)
            if isinstance(jwks_model, dict):
                jwks_dict = jwks_model
            else:
                jwks_dict = asdict(jwks_model)
            keys = JsonWebKey.import_key_set(jwks_dict)

            # Decode and verify the token
            # Note: authlib's JsonWebToken.decode returns a dict-like object
            claims = self._jwt.decode(
                id_token,
                key=keys,
            )

            # Verify audience if present
            token_aud = claims.get("aud")
            if token_aud:
                # aud can be a string or list
                if isinstance(token_aud, list):
                    if client_id not in token_aud:
                        raise AuthenticationError(
                            f"Invalid audience in ID token: expected {client_id}",
                            details={"aud": token_aud},
                        )
                elif token_aud != client_id:
                    raise AuthenticationError(
                        f"Invalid audience in ID token: expected {client_id}",
                        details={"aud": token_aud},
                    )

            # Verify issuer if provided
            if issuer:
                token_iss = claims.get("iss")
                if token_iss and token_iss != issuer:
                    raise AuthenticationError(
                        f"Invalid issuer in ID token: expected {issuer}",
                        details={"iss": token_iss},
                    )

            logger.debug("ID token signature verified successfully")
            return dict(claims)

        except (DecodeError, JoseError) as e:
            # Feature: sso-authentication, Property 3: Strict token verification
            # Requirement 11.4: Validate tokens according to protocol specifications
            # Do not fall back to unverified decoding - reject invalid tokens
            logger.error("ID token verification failed: %s", e)
            raise AuthenticationError(
                f"ID token signature verification failed: {e!s}",
                details={"error": str(e), "jwks_uri": jwks_uri},
                original_error=e,
            ) from e
        except AuthenticationError:
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Unexpected error during ID token verification: %s", e)
            raise AuthenticationError(
                f"ID token verification failed: {e!s}",
                details={"error": str(e)},
                original_error=e,
            ) from e

    async def create_authorization_url(
        self, provider: str, state: str, redirect_uri: str
    ) -> str:
        """
        Generate OAuth2 authorization URL for the specified provider.

        This method supports both OIDC discovery (automatic endpoint detection)
        and manual OAuth2 configuration.

        Args:
            provider: Provider name (e.g., 'google', 'github')
            state: Random state string for CSRF protection
            redirect_uri: Callback URL where the IdP will redirect after auth

        Returns:
            Authorization URL to redirect the user to

        Raises:
            ConfigurationError: If provider not found or misconfigured
            AuthenticationError: If URL generation fails
        """
        provider_config = self._get_provider_config(provider)

        if provider_config.type == "oauth2":
            return await self._create_oauth2_authorization_url(
                provider_config, state, redirect_uri
            )
        elif provider_config.type == "saml":
            return await self._create_saml_authorization_url(
                provider_config, state, redirect_uri
            )
        else:
            raise ConfigurationError(f"Unknown provider type: {provider_config.type}")

    async def _create_oauth2_authorization_url(
        self, provider_config: ProviderConfig, state: str, redirect_uri: str
    ) -> str:
        """
        Create OAuth2 authorization URL using Authlib.

        Supports both OIDC discovery and manual endpoint configuration.

        Args:
            provider_config: Provider configuration
            state: CSRF protection state parameter
            redirect_uri: OAuth2 redirect URI

        Returns:
            Authorization URL

        Raises:
            ConfigurationError: If configuration is invalid
            AuthenticationError: If URL generation fails
        """
        try:
            # Create OAuth2 client with basic configuration
            client = AsyncOAuth2Client(
                client_id=provider_config.client_id,
                client_secret=provider_config.client_secret,
                redirect_uri=redirect_uri,
                scope=(
                    " ".join(provider_config.scopes) if provider_config.scopes else None
                ),
            )

            # Determine authorization endpoint
            authorization_endpoint = None

            if provider_config.discovery_url:
                # OIDC Discovery: Fetch server metadata manually
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Loading OIDC discovery metadata from %s",
                        provider_config.discovery_url,
                    )
                async with httpx.AsyncClient() as http_client:
                    resp = await http_client.get(provider_config.discovery_url)
                    resp.raise_for_status()
                    metadata = resp.json()

                authorization_endpoint = metadata.get("authorization_endpoint")

                if not authorization_endpoint:
                    raise ConfigurationError(
                        "Authorization endpoint not found in OIDC discovery metadata"
                    )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Discovered authorization endpoint: %s", authorization_endpoint
                    )

            elif provider_config.authorize_url:
                # Manual configuration: Use provided endpoint
                authorization_endpoint = provider_config.authorize_url
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Using manual authorization endpoint: %s",
                        authorization_endpoint,
                    )
            else:
                raise ConfigurationError(
                    "Provider must have either discovery_url (OIDC) or authorize_url (manual OAuth2)"
                )

            # Generate authorization URL with state parameter
            uri, _ = client.create_authorization_url(
                authorization_endpoint, state=state
            )

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Generated authorization URL for provider (state=%s...)", state[:8]
                )
            return str(uri)

        except Exception as e:
            if isinstance(e, ConfigurationError | NotImplementedError):
                raise
            logger.exception("Failed to generate OAuth2 authorization URL")
            raise AuthenticationError(
                f"Failed to generate authorization URL: {e!s}",
                details={"error": str(e), "provider_type": provider_config.type},
                original_error=e,
            ) from e

    async def handle_callback(
        self,
        provider: str,
        code: str | None,
        state: str,
        redirect_uri: str,
        saml_response: str | None = None,
    ) -> SSOResult:
        """
        Process OAuth2/SAML callback and exchange code for user info.

        This method handles the OAuth2 authorization code flow:
        1. Exchange authorization code for access token
        2. Extract user identity from ID token or userinfo endpoint
        3. Return user information for authorization

        Args:
            provider: Provider name
            code: Authorization code from OAuth2 callback
            state: State parameter (for validation by caller)
            redirect_uri: Redirect URI used in original authorization request

        Returns:
            SSOResult with user info or error

        Raises:
            ConfigurationError: If provider configuration is invalid
        """
        provider_config = self._get_provider_config(provider)

        if provider_config.type == "oauth2":
            if code is None:
                raise AuthenticationError(
                    "Missing authorization code for OAuth2 callback",
                    details={"provider": provider},
                )
            return await self._handle_oauth2_callback(
                provider, provider_config, code, redirect_uri
            )
        elif provider_config.type == "saml":
            return await self._handle_saml_callback(
                provider, provider_config, saml_response, state, redirect_uri
            )
        else:
            raise ConfigurationError(f"Unknown provider type: {provider_config.type}")

    async def _handle_oauth2_callback(
        self,
        provider_name: str,
        provider_config: ProviderConfig,
        code: str,
        redirect_uri: str,
    ) -> SSOResult:
        """
        Handle OAuth2 token exchange and user info retrieval.

        Supports multiple methods for extracting user identity:
        1. OIDC ID token (preferred for OIDC providers)
        2. Userinfo endpoint (standard OAuth2/OIDC)
        3. Provider-specific APIs (e.g., GitHub)

        Args:
            provider_name: Provider name for logging
            provider_config: Provider configuration
            code: Authorization code
            redirect_uri: OAuth2 redirect URI

        Returns:
            SSOResult with user information or error
        """
        try:
            # Create OAuth2 client
            client = AsyncOAuth2Client(
                client_id=provider_config.client_id,
                client_secret=provider_config.client_secret,
                redirect_uri=redirect_uri,
            )

            # Determine endpoints
            token_endpoint = None
            userinfo_endpoint = None
            jwks_uri = None
            issuer = None

            if provider_config.discovery_url:
                # OIDC Discovery
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Loading OIDC metadata for token exchange")
                async with httpx.AsyncClient() as http_client:
                    resp = await http_client.get(provider_config.discovery_url)
                    resp.raise_for_status()
                    metadata = resp.json()
                token_endpoint = metadata.get("token_endpoint")
                userinfo_endpoint = metadata.get("userinfo_endpoint")
                jwks_uri = metadata.get("jwks_uri")
                issuer = metadata.get("issuer")
            else:
                # Manual configuration
                token_endpoint = provider_config.token_url
                userinfo_endpoint = provider_config.userinfo_url

            if not token_endpoint:
                raise ConfigurationError(
                    "Token endpoint not configured (need discovery_url or token_url)"
                )

            # Exchange authorization code for access token
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Exchanging authorization code for access token")
            token = await client.fetch_token(
                token_endpoint,
                grant_type="authorization_code",
                code=code,
            )

            if not token:
                raise AuthenticationError(
                    "Failed to retrieve access token from provider"
                )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Successfully retrieved access token")

            # Extract user identity
            user_id = None
            user_email = None

            # Method 1: Try ID token (OIDC) with signature verification
            if "id_token" in token:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Extracting user info from ID token")
                try:
                    # Verify and decode ID token using JWKS
                    claims = await self._verify_id_token(
                        id_token=token["id_token"],
                        jwks_uri=jwks_uri,
                        client_id=provider_config.client_id,
                        issuer=issuer,
                    )
                    user_id = claims.get("sub")
                    user_email = claims.get("email")
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Extracted from ID token: user_id=%s, email=%s",
                            user_id,
                            user_email,
                        )
                except AuthenticationError as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning("Failed to verify/parse ID token: %s", e)
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning("Unexpected error parsing ID token: %s", e)

            # Method 2: Try userinfo endpoint
            if (not user_id or not user_email) and userinfo_endpoint:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Fetching user info from userinfo endpoint")
                try:
                    userinfo_resp = await client.get(userinfo_endpoint)
                    userinfo_resp.raise_for_status()
                    userinfo = userinfo_resp.json()

                    if not user_id:
                        user_id = userinfo.get("sub") or userinfo.get("id")
                    if not user_email:
                        user_email = userinfo.get("email")

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Extracted from userinfo: user_id=%s, email=%s",
                            user_id,
                            user_email,
                        )
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning("Failed to fetch userinfo: %s", e)

            # Method 3: Provider-specific handling
            if not user_id or not user_email:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Attempting provider-specific user info extraction for %s",
                        provider_name,
                    )
                user_id, user_email = await self._extract_provider_specific_info(
                    provider_name, client, token, user_id, user_email
                )

            # Validate we have required information
            if not user_id:
                raise AuthenticationError(
                    "Could not determine user ID from provider response",
                    details={"provider": provider_name},
                )

            if not user_email:
                # Some providers don't expose email (privacy settings)
                # Use a placeholder but log a warning
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "No email found for user %s from provider %s, using placeholder",
                        user_id,
                        provider_name,
                    )
                user_email = f"{user_id}@{provider_name}.placeholder"

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Successfully authenticated user %s via %s", user_id, provider_name
                )

            return SSOResult(
                success=True,
                user_id=str(user_id),
                user_email=user_email,
                provider=provider_name,
            )

        except Exception as e:
            if isinstance(e, AuthenticationError | ConfigurationError):
                raise
            logger.exception(
                f"OAuth2 callback processing failed for provider {provider_name}"
            )
            return SSOResult(
                success=False,
                error=str(e),
                provider=provider_name,
            )

    # =========================================================================
    # SAML support
    # =========================================================================

    async def _create_saml_authorization_url(
        self, provider_config: ProviderConfig, state: str, redirect_uri: str
    ) -> str:
        """
        Create SAML AuthnRequest redirect URL using IdP metadata.

        The SAML flow uses HTTP-Redirect binding with a deflated, base64-encoded
        AuthnRequest. RelayState carries the state token for CSRF protection.
        """
        if not provider_config.metadata_url:
            raise ConfigurationError("SAML provider requires metadata_url")

        metadata = await self._load_saml_metadata(provider_config.metadata_url)
        sso_redirect_url = metadata.sso_redirect_url
        if not sso_redirect_url:
            raise ConfigurationError(
                "SAML metadata did not contain a SingleSignOnService redirect URL"
            )

        request_xml = self._build_saml_authn_request(
            destination=sso_redirect_url,
            issuer=provider_config.client_id,
            acs_url=redirect_uri,
            relay_state=state,
        )

        deflated = zlib.compressobj(wbits=-15)
        compressed = deflated.compress(request_xml.encode("utf-8")) + deflated.flush()
        saml_request = base64.b64encode(compressed).decode("ascii")

        query = {"SAMLRequest": saml_request, "RelayState": state}
        return f"{sso_redirect_url}?{urlencode(query)}"

    def _build_saml_authn_request(
        self, destination: str, issuer: str, acs_url: str, relay_state: str
    ) -> str:
        """
        Build a minimal AuthnRequest XML document for HTTP-Redirect binding.
        """
        request_id = f"_{uuid.uuid4().hex}"
        issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            "<samlp:AuthnRequest "
            'xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
            'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
            f'ID="{request_id}" Version="2.0" IssueInstant="{issue_instant}" '
            f'Destination="{destination}" ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
            f'AssertionConsumerServiceURL="{acs_url}" >'
            f"<saml:Issuer>{issuer}</saml:Issuer>"
            '<samlp:NameIDPolicy AllowCreate="true" '
            'Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" />'
            '<samlp:RequestedAuthnContext Comparison="minimum">'
            "<saml:AuthnContextClassRef>"
            "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
            "</saml:AuthnContextClassRef>"
            "</samlp:RequestedAuthnContext>"
            "</samlp:AuthnRequest>"
        )

    async def _load_saml_metadata(self, metadata_url: str) -> SAMLMetadata:
        """
        Fetch and parse SAML IdP metadata to extract endpoints and certificate.

        Uses LRU cache with size limit to prevent unbounded memory growth.
        """
        # Use cache if available (move to end for LRU)
        if metadata_url in self._saml_metadata_cache:
            # Move to end to mark as recently used
            self._saml_metadata_cache.move_to_end(metadata_url)
            return self._saml_metadata_cache[metadata_url]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(metadata_url)
                resp.raise_for_status()
                xml = resp.text
        except Exception as e:
            raise AuthenticationError(
                f"Failed to fetch SAML metadata: {e!s}",
                details={"metadata_url": metadata_url},
                original_error=e,
            ) from e

        try:
            root = safe_xml_parse(xml)
            ns = {
                "md": "urn:oasis:names:tc:SAML:2.0:metadata",
                "ds": "http://www.w3.org/2000/09/xmldsig#",
            }
            # Prefer HTTP-Redirect binding
            sso_services = root.findall(
                ".//md:IDPSSODescriptor/md:SingleSignOnService", ns
            )
            redirect_url = None
            post_url = None
            for svc in sso_services:
                binding = svc.attrib.get("Binding", "")
                location = svc.attrib.get("Location")
                if not location:
                    continue
                if "HTTP-Redirect" in binding and not redirect_url:
                    redirect_url = location
                if "HTTP-POST" in binding and not post_url:
                    post_url = location
            cert = None
            cert_el = root.find(
                ".//md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']/ds:KeyInfo/ds:X509Data/ds:X509Certificate",
                ns,
            )
            if cert_el is not None and cert_el.text:
                cert = cert_el.text.strip()

            parsed = SAMLMetadata(
                sso_redirect_url=redirect_url or post_url,
                signing_cert=cert,
                entity_id=root.attrib.get("entityID"),
            )
            # Add to cache with LRU eviction if size limit exceeded
            if metadata_url in self._saml_metadata_cache:
                # Update existing entry and move to end
                self._saml_metadata_cache[metadata_url] = parsed
                self._saml_metadata_cache.move_to_end(metadata_url)
            else:
                # Add new entry
                self._saml_metadata_cache[metadata_url] = parsed
                # Evict oldest entries if cache exceeds size limit
                while len(self._saml_metadata_cache) > MAX_SAML_METADATA_CACHE_SIZE:
                    oldest_url, _ = self._saml_metadata_cache.popitem(last=False)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Evicted SAML metadata cache entry for %s (cache size limit: %d)",
                            oldest_url,
                            MAX_SAML_METADATA_CACHE_SIZE,
                        )
            return parsed
        except Exception as e:
            raise AuthenticationError(
                f"Failed to parse SAML metadata: {e!s}",
                details={"metadata_url": metadata_url},
                original_error=e,
            ) from e

    async def _handle_saml_callback(
        self,
        provider_name: str,
        provider_config: ProviderConfig,
        saml_response: str | None,
        relay_state: str,
        acs_url: str,
    ) -> SSOResult:
        """
        Handle SAML Response sent to the Assertion Consumer Service (callback).
        """
        if not saml_response:
            raise AuthenticationError(
                "Missing SAMLResponse in callback",
                details={"provider": provider_name},
            )

        try:
            xml_bytes = base64.b64decode(saml_response)
            root = safe_xml_parse(xml_bytes)
        except Exception as e:
            raise AuthenticationError(
                f"Failed to decode SAMLResponse: {e!s}",
                details={"provider": provider_name},
                original_error=e,
            ) from e

        ns = {
            "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
            "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
        }

        status_code_el = root.find(".//samlp:StatusCode", ns)
        status_value = (
            status_code_el.attrib.get("Value") if status_code_el is not None else None
        )
        if status_value and "Success" not in status_value:
            raise AuthenticationError(
                f"SAML authentication failed with status {status_value}",
                details={"provider": provider_name},
            )

        assertion = root.find(".//saml:Assertion", ns)
        if assertion is None:
            raise AuthenticationError(
                "No Assertion found in SAMLResponse",
                details={"provider": provider_name},
            )

        # Enforce signing certificate match (basic binding)
        metadata = None
        if provider_config.metadata_url:
            metadata = self._saml_metadata_cache.get(provider_config.metadata_url) or (
                await self._load_saml_metadata(provider_config.metadata_url)
            )
        signing_cert_expected = metadata.signing_cert if metadata else None

        sig_ns = {"ds": "http://www.w3.org/2000/09/xmldsig#"}
        sig_cert_el = root.find(
            ".//ds:Signature/ds:KeyInfo/ds:X509Data/ds:X509Certificate", sig_ns
        )
        sig_cert = (
            sig_cert_el.text.strip()
            if sig_cert_el is not None and sig_cert_el.text
            else None
        )

        if signing_cert_expected:
            if not sig_cert:
                raise AuthenticationError(
                    "SAML response missing signing certificate",
                    details={"provider": provider_name},
                )
            # Normalize by stripping whitespace/newlines
            normalized_expected = "".join(signing_cert_expected.split())
            normalized_received = "".join(sig_cert.split())
            if normalized_expected != normalized_received:
                raise AuthenticationError(
                    "SAML response signing certificate does not match IdP metadata",
                    details={"provider": provider_name},
                )

        # Validate Conditions (audience + expiry)
        conditions = assertion.find("saml:Conditions", ns)
        if conditions is not None:
            not_on_or_after = conditions.attrib.get("NotOnOrAfter")
            if not_on_or_after:
                try:
                    expiry = datetime.fromisoformat(
                        not_on_or_after.replace("Z", "+00:00")
                    )
                    if expiry <= datetime.now(timezone.utc):
                        raise AuthenticationError(
                            "SAML assertion is expired",
                            details={"provider": provider_name},
                        )
                except ValueError:
                    raise AuthenticationError(
                        "Invalid NotOnOrAfter timestamp in SAML assertion",
                        details={"provider": provider_name},
                    )

            audience_valid = False
            audience_restrictions = conditions.findall("saml:AudienceRestriction", ns)
            for restriction in audience_restrictions:
                for aud in restriction.findall("saml:Audience", ns):
                    if aud.text and aud.text == provider_config.client_id:
                        audience_valid = True
                        break
            if audience_restrictions and not audience_valid:
                raise AuthenticationError(
                    "SAML assertion audience does not match client_id",
                    details={"provider": provider_name},
                )

        # Extract subject
        name_id = assertion.find("saml:Subject/saml:NameID", ns)
        user_id = name_id.text if name_id is not None else None

        # Extract attributes (email, etc.)
        attributes = {}
        for attr in assertion.findall(".//saml:Attribute", ns):
            name = attr.attrib.get("Name") or ""
            values = [
                val.text for val in attr.findall("saml:AttributeValue", ns) if val.text
            ]
            if values:
                attributes[name] = values

        user_email = None
        for key, values in attributes.items():
            if "email" in key.lower() and values:
                user_email = values[0]
                break

        if not user_id:
            raise AuthenticationError(
                "SAML assertion missing NameID",
                details={"provider": provider_name},
            )

        if not user_email:
            logger.warning(
                "No email attribute found in SAML assertion for %s - using placeholder",
                provider_name,
            )
            user_email = f"{user_id}@{provider_name}.placeholder"

        return SSOResult(
            success=True,
            user_id=str(user_id),
            user_email=user_email,
            provider=provider_name,
        )

    async def _extract_provider_specific_info(
        self,
        provider_name: str,
        client: AsyncOAuth2Client,
        token: dict,
        current_user_id: str | None,
        current_email: str | None,
    ) -> tuple[str | None, str | None]:
        """
        Extract user info using provider-specific APIs.

        Some providers (like GitHub) don't follow standard OIDC patterns
        and require custom API calls to get user information.

        Args:
            provider_name: Provider name
            client: OAuth2 client with valid access token
            token: Token response from provider
            current_user_id: Already extracted user ID (if any)
            current_email: Already extracted email (if any)

        Returns:
            Tuple of (user_id, email)
        """
        user_id = current_user_id
        email = current_email

        try:
            if provider_name == "github":
                # GitHub uses /user endpoint for user info
                if not user_id or not email:
                    user_resp = await client.get("https://api.github.com/user")
                    user_resp.raise_for_status()
                    user_data = user_resp.json()

                    if not user_id:
                        user_id = str(user_data.get("id") or user_data.get("login"))

                    if not email:
                        # GitHub email might be private, try /user/emails endpoint
                        email = user_data.get("email")
                        if not email:
                            emails_resp = await client.get(
                                "https://api.github.com/user/emails"
                            )
                            if emails_resp.status_code == 200:
                                emails = emails_resp.json()
                                # Find primary email
                                for email_obj in emails:
                                    if email_obj.get("primary"):
                                        email = email_obj.get("email")
                                        break
                                # Fallback to first email
                                if not email and emails:
                                    email = emails[0].get("email")

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "GitHub-specific extraction: user_id=%s, email=%s",
                            user_id,
                            email,
                        )

            elif provider_name == "linkedin":
                # LinkedIn v2 API requires specific endpoints
                if not user_id:
                    # Get user profile
                    profile_resp = await client.get(
                        "https://api.linkedin.com/v2/me",
                        headers={"X-Restli-Protocol-Version": "2.0.0"},
                    )
                    profile_resp.raise_for_status()
                    profile = profile_resp.json()
                    user_id = profile.get("id")

                if not email:
                    # Get email address
                    email_resp = await client.get(
                        "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))",
                        headers={"X-Restli-Protocol-Version": "2.0.0"},
                    )
                    if email_resp.status_code == 200:
                        email_data = email_resp.json()
                        elements = email_data.get("elements", [])
                        if elements:
                            email = elements[0].get("handle~", {}).get("emailAddress")

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "LinkedIn-specific extraction: user_id=%s, email=%s",
                        user_id,
                        email,
                    )

        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Provider-specific extraction failed for %s: %s", provider_name, e
                )

        return user_id, email
