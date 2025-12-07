from __future__ import annotations

import logging
import os
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.interfaces.activity_tracker_interface import IConnectionActivityTracker
from src.core.interfaces.backend_factory_interface import IBackendFactory
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.backend_registry import BackendRegistry

if TYPE_CHECKING:
    from src.core.services.health.backend_notifier import BackendHealthNotifier
    from src.core.services.health.endpoint_registry import EndpointRegistry

logger = logging.getLogger(__name__)


class BackendFactory(IBackendFactory):
    """Factory for creating LLM backends.

    This factory creates and configures backends based on type and configuration.
    """

    def __init__(
        self,
        httpx_client: httpx.AsyncClient,
        backend_registry: BackendRegistry,
        config: AppConfig,
        translation_service: ITranslationService,
        endpoint_registry: EndpointRegistry | None = None,
        backend_notifier: BackendHealthNotifier | None = None,
        activity_tracker: IConnectionActivityTracker | None = None,
    ) -> None:
        """Initialize the backend factory.

        Args:
            httpx_client: HTTP client for API calls
            backend_registry: The registry for discovering backends
            config: The application configuration
            translation_service: Service for translation/format conversion
            endpoint_registry: Optional registry for health check tracking
            backend_notifier: Optional notifier for health event subscriptions
            activity_tracker: Optional tracker for connection activity monitoring
        """
        self._client = httpx_client
        self._backend_registry = backend_registry
        self._config = config  # Stored config
        self._translation_service = translation_service
        self._endpoint_registry = endpoint_registry
        self._backend_notifier = backend_notifier
        self._activity_tracker = activity_tracker

    def create_backend(
        self, backend_type: str, config: AppConfig | None = None
    ) -> LLMBackend:
        """Create a backend instance of the specified type.

        Args:
            backend_type: The type of backend to create
            config: The application configuration

        Returns:
            A new LLM backend instance

        Raises:
            ValueError: If the backend type is not supported
        """
        backend_factory = self._backend_registry.get_backend_factory(backend_type)
        # Backend connectors only accept the client and config in constructor
        effective_config = config if config is not None else self._config
        return backend_factory(
            self._client, effective_config, self._translation_service
        )

    def unregister_backend(self, backend_name: str) -> None:
        """Unregister a backend from health checks.

        Args:
            backend_name: The unique backend instance name.
        """
        if self._endpoint_registry:
            self._endpoint_registry.unregister_backend(backend_name)

    def unregister_backend_notifications(self, backend: LLMBackend) -> None:
        """Unregister a backend from health notifications if enabled."""
        if self._backend_notifier is None:
            return
        try:
            self._backend_notifier.unregister_backend(backend)
        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to unregister backend from notifications: %s", exc
                )

    async def initialize_backend(
        self, backend: LLMBackend, init_config: dict[str, Any]
    ) -> None:
        """Initialize a backend with configuration.

        Args:
            backend: The backend to initialize
            init_config: The configuration for the backend
        """
        await backend.initialize(**init_config)

    async def ensure_backend(
        self,
        backend_type: str,
        app_config: AppConfig,  # Added app_config
        backend_config: BackendConfig | None = None,
    ) -> LLMBackend:
        """Create and initialize a backend given a canonical BackendConfig.

        This method centralizes connector initialization logic so callers
        don't need to duplicate api_key/url shaping and backend-specific
        parameters.
        """
        logger = logging.getLogger(__name__)

        # Resolve connector from instance name (e.g. "openai.1" -> "openai")
        connector_type = (
            backend_type.split(".")[0] if "." in backend_type else backend_type
        )

        # Check if connector exists; fallback to original behavior if needed
        # (legacy names might contain dots? unlikely given validation, but let's be robust)
        if (
            connector_type not in self._backend_registry.get_registered_backends()
            and backend_type in self._backend_registry.get_registered_backends()
        ):
            connector_type = backend_type

        # Build init_config from BackendConfig
        init_config: dict[str, Any] = {}

        if backend_config is not None:
            # Pass api_key directly (now a string)
            init_config["api_key"] = backend_config.api_key
            if backend_config.api_url:
                init_config["api_base_url"] = backend_config.api_url

            # Pass credentials_path if available
            if backend_config.credentials_path:
                init_config["credentials_path"] = backend_config.credentials_path

            # Pass supported_input_types if available
            if backend_config.supported_input_types:
                init_config["supported_input_types"] = (
                    backend_config.supported_input_types
                )

            for k, v in backend_config.extra.items():
                init_config[k] = v

        # SECURITY: Removed test environment detection and automatic test key injection
        # Production code should never detect test environment or auto-configure credentials
        default_backend_env = os.environ.get("LLM_BACKEND")
        current_api_key = init_config.get("api_key")

        if not current_api_key:
            env_key_mapping: dict[str, dict[str, str]] = {
                "minimax": {
                    "api_key_env": "MINIMAX_API_KEY",
                    "api_base_url_env": "MINIMAX_API_BASE_URL",
                    "default_api_base_url": "https://api.minimax.io/v1",
                }
            }
            env_spec = env_key_mapping.get(connector_type)  # Use connector_type
            if env_spec:
                # Use standard env var for API key (no collection)
                api_key_env = env_spec["api_key_env"]
                current_api_key = os.environ.get(api_key_env)
                if current_api_key:
                    init_config["api_key"] = current_api_key
                    api_base_url = init_config.get("api_base_url")
                    if not api_base_url:
                        init_config["api_base_url"] = os.environ.get(
                            env_spec["api_base_url_env"],
                            env_spec["default_api_base_url"],
                        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Backend factory for {backend_type} (connector={connector_type}): current_api_key={current_api_key}, default_backend_env={default_backend_env}"
            )

        if current_api_key and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Using provided API key for {backend_type}: {current_api_key[:20] if current_api_key else 'None'}..."
            )

        # Backend-specific augmentations
        if connector_type == "anthropic":
            init_config["key_name"] = connector_type
        elif connector_type == "openrouter":
            from src.core.config.app_config import get_openrouter_headers

            init_config["key_name"] = connector_type
            init_config["openrouter_headers_provider"] = get_openrouter_headers
            if "api_base_url" not in init_config:
                init_config["api_base_url"] = "https://openrouter.ai/api/v1"
        elif connector_type == "gemini":
            init_config["key_name"] = connector_type
            # Map api_base_url to gemini_api_base_url for Gemini backend
            if "api_base_url" in init_config:
                init_config["gemini_api_base_url"] = init_config["api_base_url"]
            elif "gemini_api_base_url" not in init_config:
                init_config["gemini_api_base_url"] = (
                    "https://generativelanguage.googleapis.com"
                )

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Factory initializing backend {backend_type} (connector={connector_type}) with {init_config}"
            )

        # Step 1: Create the backend instance using connector type
        backend = self.create_backend(connector_type, app_config)  # Modified

        # Step 2: Initialize it with the config
        await self.initialize_backend(backend, init_config)

        # Step 3: Set the instance name on the backend
        if hasattr(backend, "backend_type"):
            # We override backend_type to be the instance name so logging and tracking uses the unique name
            # This might be risky if logic depends on backend_type being the connector name.
            # Let's check if there is another field. `name` attribute?
            # Base LLMBackend has `backend_type`.
            # If we change it, `isinstance` checks are fine, but checks like `if backend.backend_type == 'openai'` might fail.
            # But we want metrics to be per-instance.
            # Let's keep backend_type as connector, and add instance_name if possible?
            # Or just use the fact that it's a unique instance object.

            # Wait, `BackendService` uses `backend_type` for rate limiting keys `f"backend:{backend_type}"`.
            # If we don't change it, all instances share rate limits!
            # Requirement says: "Granular Rate Limiting ... Instance Level".
            # So we MUST change the identifier used for rate limiting.

            # Let's update backend_type to be the instance name.
            # Update backend_type attribute if possible (may fail if property without setter)
            with suppress(AttributeError):
                backend.backend_type = backend_type

        # Step 4: Store the API URL on the backend and register for health checks
        api_url = init_config.get("api_base_url") or init_config.get(
            "gemini_api_base_url"
        )
        if api_url:
            # Store API URL on backend for health-aware interface
            backend.api_url = api_url

        # Step 5: Register the backend's API URL in the endpoint registry for health checks
        self._register_endpoint_for_health_check(backend_type, init_config)

        # Step 6: Register backend for health notifications
        self._register_backend_for_notifications(backend)

        # Step 7: Configure activity tracking if available
        self._configure_activity_tracking(backend, backend_type)

        return backend

    def _configure_activity_tracking(
        self, backend: LLMBackend, instance_name: str
    ) -> None:
        """Configure activity tracking for a backend instance.

        Args:
            backend: The backend instance to configure.
            instance_name: The unique name for this backend instance.
        """
        if self._activity_tracker is None:
            return

        try:
            backend.set_activity_tracker(self._activity_tracker, instance_name)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Configured activity tracking for backend %s", instance_name
                )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to configure activity tracking for backend %s: %s",
                    instance_name,
                    e,
                )

    def _register_endpoint_for_health_check(
        self,
        backend_name: str,
        init_config: dict[str, Any],
    ) -> None:
        """Register a backend's API URL in the endpoint registry for health checks.

        Args:
            backend_name: The unique backend instance name.
            init_config: The initialization config containing API URL.
        """
        if self._endpoint_registry is None:
            return

        # Determine the API URL from the init config
        api_url = init_config.get("api_base_url") or init_config.get(
            "gemini_api_base_url"
        )
        if not api_url:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "No API URL found for backend %s, skipping health check registration",
                    backend_name,
                )
            return

        try:
            self._endpoint_registry.register_backend(backend_name, api_url)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register backend %s for health checks: %s",
                    backend_name,
                    e,
                )

    def _register_backend_for_notifications(self, backend: LLMBackend) -> None:
        """Register a backend to receive health state notifications.

        Args:
            backend: The backend instance to register for notifications.
        """
        if self._backend_notifier is None:
            return

        if not backend.api_url:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Backend has no API URL, skipping notification registration"
                )
            return

        try:
            self._backend_notifier.register_backend(backend)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register backend for health notifications: %s",
                    e,
                )

    @staticmethod
    def create(service_provider: IServiceProvider) -> BackendFactory:
        """Create a backend factory using the service provider.

        This is a convenience method for dependency injection.

        Args:
            service_provider: The service provider to get dependencies from

        Returns:
            A new BackendFactory instance
        """
        # Resolve the registered BackendFactory from the DI container
        # to avoid manual instantiation and adhere to DIP.
        return service_provider.get_required_service(BackendFactory)
