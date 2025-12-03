"""
Strategy interfaces for Gemini OAuth connectors.

This module defines protocols (interfaces) for the Strategy Pattern implementation
that allows different Gemini OAuth backends to be composed from reusable components.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import httpx

    from src.core.domain.responses import ResponseEnvelope


@runtime_checkable
class ICredentialProvider(Protocol):
    """Protocol for OAuth credential providers.

    Implementations load credentials from different sources:
    - FileCredentialProvider: JSON file (oauth_creds.json)
    - AntigravitySQLiteCredentialProvider: SQLite database (state.vscdb)
    """

    async def load(
        self, force_reload: bool = False, silent: bool = False
    ) -> dict[str, Any] | None:
        """Load OAuth credentials from the source.

        Args:
            force_reload: If True, bypass cache and force reload.
            silent: If True, suppress INFO level logging.

        Returns:
            Credentials dictionary or None if loading failed.
        """
        ...

    def validate(
        self, credentials: dict[str, Any], silent: bool = False
    ) -> tuple[bool, list[str]]:
        """Validate the structure and content of OAuth credentials.

        Args:
            credentials: The credentials dictionary to validate.
            silent: If True, suppress INFO level logging.

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        ...

    def get_path(self) -> Path | None:
        """Get the path to the credentials source.

        Returns:
            Path to the credentials file/database, or None if not applicable.
        """
        ...

    def compute_fingerprint(self, credentials: dict[str, Any]) -> str:
        """Compute a stable fingerprint for the credentials.

        Args:
            credentials: The credentials dictionary.

        Returns:
            SHA-256 hash of the relevant credential fields.
        """
        ...


@runtime_checkable
class IEndpointConfig(Protocol):
    """Protocol for API endpoint configuration.

    Implementations provide endpoint URLs and headers for different backends:
    - StandardCodeAssistEndpoint: cloudcode-pa.googleapis.com
    - AntigravitySandboxEndpoint: daily-cloudcode-pa.sandbox.googleapis.com
    """

    def get_base_url(self) -> str:
        """Get the base URL for the API endpoint.

        Returns:
            The API base URL string.
        """
        ...

    def get_api_headers(self, credentials: dict[str, Any] | None) -> dict[str, str]:
        """Get headers for API requests (used with httpx client).

        Args:
            credentials: Optional credentials dictionary for Authorization header.

        Returns:
            Dictionary of HTTP headers.
        """
        ...

    def get_session_headers(self) -> dict[str, str]:
        """Get headers for AuthorizedSession requests (used with requests library).

        Returns:
            Dictionary of HTTP headers (e.g., custom User-Agent).
        """
        ...


@runtime_checkable
class IRequestBodyBuilder(Protocol):
    """Protocol for building backend-specific request body structures.

    Implementations format the request body differently:
    - StandardRequestBodyBuilder: user_prompt_id format
    - AntigravityRequestBodyBuilder: requestId, userAgent, requestType format
    """

    def build(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        inner_request: dict[str, Any],
        user_prompt_id_generator: Any = None,
    ) -> dict[str, Any]:
        """Build the outer request body wrapper for Code Assist API.

        Args:
            effective_model: The model name to use.
            project_id: The project ID from loadCodeAssist.
            request_data: The original request data (for generating IDs).
            inner_request: The inner request with contents, generationConfig, etc.
            user_prompt_id_generator: Optional callable to generate user_prompt_id.

        Returns:
            Complete request body dict ready to send to the API.
        """
        ...


@runtime_checkable
class IProjectDiscoveryStrategy(Protocol):
    """Protocol for project ID discovery strategies.

    Implementations handle different project discovery flows:
    - FreeTierProjectDiscovery: free-tier onboarding
    - PaidTierProjectDiscovery: paid-tier onboarding
    - AntigravityProjectDiscovery: Antigravity-specific flow
    """

    async def discover(
        self,
        auth_session: Any,
        credentials: dict[str, Any] | None,
        base_url: str,
        cached_project_id: str | None = None,
    ) -> str:
        """Discover or retrieve the project ID for Code Assist API.

        Args:
            auth_session: The authorized session for API calls.
            credentials: OAuth credentials dictionary.
            base_url: The API base URL.
            cached_project_id: Previously discovered project ID, if any.

        Returns:
            The discovered project ID string.
        """
        ...


@runtime_checkable
class IModelDiscoveryStrategy(Protocol):
    """Protocol for model discovery strategies.

    Implementations handle model enumeration differently:
    - ApiModelDiscovery: Calls fetchAvailableModels API
    - FallbackModelDiscovery: Returns hardcoded model list
    """

    async def discover(
        self,
        client: "httpx.AsyncClient",
        headers: dict[str, str],
        base_url: str,
    ) -> list[str]:
        """Discover available models from the backend.

        Args:
            client: The HTTP client for API calls.
            headers: HTTP headers including authorization.
            base_url: The API base URL.

        Returns:
            List of available model names.
        """
        ...

    def get_fallback_models(self) -> list[str]:
        """Get the fallback model list when API discovery fails.

        Returns:
            List of fallback model names.
        """
        ...


@runtime_checkable
class IResponsePostProcessor(Protocol):
    """Protocol for response post-processing.

    Implementations can modify responses after they're received:
    - NoOpResponsePostProcessor: Pass-through, no modifications
    - XmlToolCallPostProcessor: Parse XML tool calls (Antigravity/Claude)
    """

    def process(
        self,
        response: "ResponseEnvelope",
        effective_model: str,
    ) -> "ResponseEnvelope":
        """Post-process a response envelope.

        Args:
            response: The response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The processed response envelope.
        """
        ...

    async def process_streaming(
        self,
        response: Any,
        effective_model: str,
    ) -> Any:
        """Post-process a streaming response.

        Args:
            response: The streaming response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The processed streaming response envelope.
        """
        ...


@runtime_checkable
class IHealthCheckStrategy(Protocol):
    """Protocol for health check strategies.

    Implementations perform backend-specific health checks:
    - ApiHealthCheck: Uses fetchAvailableModels endpoint
    - TokenHealthCheck: Only verifies token is refreshable
    """

    async def check(
        self,
        client: "httpx.AsyncClient",
        headers: dict[str, str],
        base_url: str,
        refresh_token_callback: Any = None,
    ) -> bool:
        """Perform a health check on the backend.

        Args:
            client: The HTTP client for API calls.
            headers: HTTP headers including authorization.
            base_url: The API base URL.
            refresh_token_callback: Optional callback to refresh token.

        Returns:
            True if the backend is healthy, False otherwise.
        """
        ...


__all__ = [
    "ICredentialProvider",
    "IEndpointConfig",
    "IHealthCheckStrategy",
    "IModelDiscoveryStrategy",
    "IProjectDiscoveryStrategy",
    "IRequestBodyBuilder",
    "IResponsePostProcessor",
]
