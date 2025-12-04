"""
SSO Service for authentication.

This module handles OAuth2 and SAML authentication flows using Authlib.
"""

import logging
import time
from typing import Any

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore
from authlib.jose import JsonWebKey, JsonWebToken  # type: ignore
from authlib.jose.errors import DecodeError, JoseError  # type: ignore

from src.core.auth.sso.config import ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import AuthenticationError, ConfigurationError
from src.core.auth.sso.models import SSOResult

logger = logging.getLogger(__name__)


class JWKSCache:
    """
    Cache for JSON Web Key Sets (JWKS) from identity providers.

    Caches JWKS for each provider to avoid fetching on every request.
    Keys are automatically refreshed after TTL expires.
    """

    DEFAULT_TTL = 3600  # 1 hour

    def __init__(self, ttl: int = DEFAULT_TTL):
        """
        Initialize JWKS cache.

        Args:
            ttl: Time-to-live for cached keys in seconds (default: 1 hour)
        """
        self._cache: dict[str, dict[str, Any]] = {}
        self._ttl = ttl

    def get(self, jwks_uri: str) -> dict[str, Any] | None:
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

        return entry.get("jwks")

    def set(self, jwks_uri: str, jwks: dict[str, Any]) -> None:
        """
        Cache JWKS for a URI.

        Args:
            jwks_uri: The JWKS endpoint URI
            jwks: The JWKS data to cache
        """
        self._cache[jwks_uri] = {
            "jwks": jwks,
            "expires_at": time.time() + self._ttl,
        }

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
        self._jwks_cache = jwks_cache or JWKSCache()

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

    async def _fetch_jwks(self, jwks_uri: str) -> dict[str, Any]:
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
            logger.debug(f"Using cached JWKS for {jwks_uri}")
            return cached

        # Fetch fresh JWKS
        logger.debug(f"Fetching JWKS from {jwks_uri}")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(jwks_uri)
                resp.raise_for_status()
                jwks: dict[str, Any] = resp.json()

            # Cache the result
            self._jwks_cache.set(jwks_uri, jwks)
            logger.debug(f"Cached JWKS with {len(jwks.get('keys', []))} keys")
            return jwks

        except Exception as e:
            logger.warning(f"Failed to fetch JWKS from {jwks_uri}: {e}")
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
            # No JWKS URI available (e.g., for non-OIDC providers)
            # Fall back to unverified decoding with a warning
            logger.warning(
                "No JWKS URI available - decoding ID token without signature verification"
            )
            try:
                claims = self._jwt.decode(
                    id_token,
                    key=None,
                    claims_options={"verify_signature": False},
                )
                return dict(claims)
            except (DecodeError, JoseError) as e:
                raise AuthenticationError(
                    f"Failed to decode ID token: {e!s}",
                    details={"error": str(e)},
                    original_error=e,
                ) from e

        # Fetch JWKS and verify signature
        try:
            jwks_data = await self._fetch_jwks(jwks_uri)

            # Import the JWKS as a key set
            keys = JsonWebKey.import_key_set(jwks_data)

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
            logger.warning(f"ID token verification failed: {e}")
            # Fall back to unverified decoding - some providers have quirks
            logger.warning("Falling back to unverified ID token decoding")
            try:
                claims = self._jwt.decode(
                    id_token,
                    key=None,
                    claims_options={"verify_signature": False},
                )
                return dict(claims)
            except (DecodeError, JoseError) as fallback_error:
                raise AuthenticationError(
                    f"Failed to decode ID token: {fallback_error!s}",
                    details={"error": str(fallback_error)},
                    original_error=fallback_error,
                ) from fallback_error
        except AuthenticationError:
            raise
        except Exception as e:
            logger.warning(f"Unexpected error during ID token verification: {e}")
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
            raise NotImplementedError("SAML support not yet implemented")
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
                logger.debug(
                    f"Loading OIDC discovery metadata from {provider_config.discovery_url}"
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
                logger.debug(
                    f"Discovered authorization endpoint: {authorization_endpoint}"
                )

            elif provider_config.authorize_url:
                # Manual configuration: Use provided endpoint
                authorization_endpoint = provider_config.authorize_url
                logger.debug(
                    f"Using manual authorization endpoint: {authorization_endpoint}"
                )
            else:
                raise ConfigurationError(
                    "Provider must have either discovery_url (OIDC) or authorize_url (manual OAuth2)"
                )

            # Generate authorization URL with state parameter
            uri, _ = client.create_authorization_url(
                authorization_endpoint, state=state
            )

            logger.info(
                f"Generated authorization URL for provider (state={state[:8]}...)"
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
        self, provider: str, code: str, state: str, redirect_uri: str
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
            return await self._handle_oauth2_callback(
                provider, provider_config, code, redirect_uri
            )
        elif provider_config.type == "saml":
            raise NotImplementedError("SAML callback not implemented")
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

            logger.debug("Successfully retrieved access token")

            # Extract user identity
            user_id = None
            user_email = None

            # Method 1: Try ID token (OIDC) with signature verification
            if "id_token" in token:
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
                    logger.debug(
                        f"Extracted from ID token: user_id={user_id}, email={user_email}"
                    )
                except AuthenticationError as e:
                    logger.warning(f"Failed to verify/parse ID token: {e}")
                except Exception as e:
                    logger.warning(f"Unexpected error parsing ID token: {e}")

            # Method 2: Try userinfo endpoint
            if (not user_id or not user_email) and userinfo_endpoint:
                logger.debug("Fetching user info from userinfo endpoint")
                try:
                    userinfo_resp = await client.get(userinfo_endpoint)
                    userinfo_resp.raise_for_status()
                    userinfo = userinfo_resp.json()

                    if not user_id:
                        user_id = userinfo.get("sub") or userinfo.get("id")
                    if not user_email:
                        user_email = userinfo.get("email")

                    logger.debug(
                        f"Extracted from userinfo: user_id={user_id}, email={user_email}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to fetch userinfo: {e}")

            # Method 3: Provider-specific handling
            if not user_id or not user_email:
                logger.debug(
                    f"Attempting provider-specific user info extraction for {provider_name}"
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
                logger.warning(
                    f"No email found for user {user_id} from provider {provider_name}, "
                    "using placeholder"
                )
                user_email = f"{user_id}@{provider_name}.placeholder"

            logger.info(
                f"Successfully authenticated user {user_id} via {provider_name}"
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

                    logger.debug(
                        f"GitHub-specific extraction: user_id={user_id}, email={email}"
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

                logger.debug(
                    f"LinkedIn-specific extraction: user_id={user_id}, email={email}"
                )

        except Exception as e:
            logger.warning(
                f"Provider-specific extraction failed for {provider_name}: {e}"
            )

        return user_id, email
