"""
Failover Service

This module implements the failover policy logic for the backend service.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from src.constants import SUPPORTED_BACKENDS
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.interfaces.configuration import IConfig

logger = logging.getLogger(__name__)


class FailoverPolicy(str, Enum):
    """Failover policy types."""
    
    # Single backend, all keys
    KEYS = "k"
    
    # Multiple backends, first key for each
    MODELS = "m"
    
    # All keys for all models
    KEYS_THEN_MODELS = "km"
    
    # Round-robin keys across models
    MODELS_THEN_KEYS = "mk"


class FailoverAttempt:
    """Represents a single failover attempt."""
    
    def __init__(self, backend: str, model: str, key_name: str, api_key: str):
        """Initialize a failover attempt.
        
        Args:
            backend: Backend type
            model: Model name
            key_name: API key name
            api_key: API key value
        """
        self.backend = backend
        self.model = model
        self.key_name = key_name
        self.api_key = api_key
    
    def __str__(self) -> str:
        """String representation of the attempt."""
        return f"FailoverAttempt(backend={self.backend}, model={self.model}, key_name={self.key_name})"


class FailoverService:
    """Service for managing failover policies."""
    
    def __init__(self, config: IConfig):
        """Initialize the failover service.
        
        Args:
            config: Application configuration
        """
        self._config = config
    
    def get_failover_attempts(
        self, 
        backend_config: BackendConfiguration,
        effective_model: str,
        current_backend_type: str,
    ) -> list[FailoverAttempt]:
        """Get failover attempts based on the policy.
        
        Args:
            backend_config: Backend configuration
            effective_model: The model to use
            current_backend_type: The current backend type
            
        Returns:
            List of failover attempts
        """
        route = backend_config.failover_routes.get(effective_model)
        if not route:
            return [self._create_default_attempt(current_backend_type, effective_model)]
        
        elements = route.get("elements", [])
        normalized_elements = self._normalize_elements(elements)
        policy = route.get("policy", FailoverPolicy.KEYS)
        
        if policy == FailoverPolicy.KEYS and normalized_elements:
            return self._get_attempts_for_single_backend(normalized_elements[0])
        if policy == FailoverPolicy.MODELS:
            return self._get_attempts_for_models(normalized_elements)
        if policy == FailoverPolicy.KEYS_THEN_MODELS:
            return self._get_attempts_for_all_keys_all_models(normalized_elements)
        if policy == FailoverPolicy.MODELS_THEN_KEYS:
            return self._get_attempts_round_robin_keys(normalized_elements)
        
        return [self._create_default_attempt(current_backend_type, effective_model)]
    
    def _normalize_elements(self, elements: Any) -> list[str]:
        """Normalize route elements.
        
        Args:
            elements: Route elements
            
        Returns:
            Normalized list of elements
        """
        if isinstance(elements, dict):
            return list(elements.values())
        if isinstance(elements, list):
            return elements
        return []
    
    def _get_keys_for_backend(self, backend: str) -> list[tuple[str, str]]:
        """Get API keys for a backend.
        
        Args:
            backend: Backend type
            
        Returns:
            List of (key_name, key_value) tuples
        """
        if backend not in SUPPORTED_BACKENDS:
            logger.warning(f"Unsupported backend: {backend}")
            return []
        
        # Get keys from config
        keys = []
        
        # Check for backend-specific keys
        if backend == "openai":
            openai_keys = self._config.get("openai_api_keys", {})
            keys.extend(openai_keys.items())
        elif backend == "anthropic":
            anthropic_keys = self._config.get("anthropic_api_keys", {})
            keys.extend(anthropic_keys.items())
        elif backend == "gemini":
            gemini_keys = self._config.get("gemini_api_keys", {})
            keys.extend(gemini_keys.items())
        elif backend == "openrouter":
            openrouter_keys = self._config.get("openrouter_api_keys", {})
            keys.extend(openrouter_keys.items())
        elif backend == "qwen_oauth":
            qwen_oauth_keys = self._config.get("qwen_oauth_tokens", {})
            keys.extend(qwen_oauth_keys.items())
        elif backend == "zai":
            zai_keys = self._config.get("zai_api_keys", {})
            keys.extend(zai_keys.items())
        
        return keys
    
    def _create_default_attempt(self, backend: str, model: str) -> FailoverAttempt:
        """Create a default failover attempt.
        
        Args:
            backend: Backend type
            model: Model name
            
        Returns:
            Default failover attempt
            
        Raises:
            ValueError: If no API keys are configured for the backend
        """
        keys = self._get_keys_for_backend(backend)
        if not keys:
            raise ValueError(f"No API keys configured for the default backend: {backend}")
        
        key_name, key_value = keys[0]
        return FailoverAttempt(backend, model, key_name, key_value)
    
    def _get_attempts_for_single_backend(self, element: str) -> list[FailoverAttempt]:
        """Get failover attempts for a single backend with all keys.
        
        Args:
            element: Backend:model element
            
        Returns:
            List of failover attempts
        """
        if ":" not in element:
            logger.warning(f"Invalid element format: {element}")
            return []
        
        backend, model = element.split(":", 1)
        keys = self._get_keys_for_backend(backend)
        
        return [
            FailoverAttempt(backend, model, key_name, key_value)
            for key_name, key_value in keys
        ]
    
    def _get_attempts_for_models(self, elements: list[str]) -> list[FailoverAttempt]:
        """Get failover attempts for multiple backends, using the first key for each.
        
        Args:
            elements: List of backend:model elements
            
        Returns:
            List of failover attempts
        """
        attempts = []
        
        for element in elements:
            if ":" not in element:
                logger.warning(f"Invalid element format: {element}")
                continue
            
            backend, model = element.split(":", 1)
            keys = self._get_keys_for_backend(backend)
            
            if keys:
                key_name, key_value = keys[0]
                attempts.append(FailoverAttempt(backend, model, key_name, key_value))
        
        return attempts
    
    def _get_attempts_for_all_keys_all_models(self, elements: list[str]) -> list[FailoverAttempt]:
        """Get failover attempts for all keys for all models.
        
        Args:
            elements: List of backend:model elements
            
        Returns:
            List of failover attempts
        """
        attempts = []
        
        for element in elements:
            if ":" not in element:
                logger.warning(f"Invalid element format: {element}")
                continue
            
            backend, model = element.split(":", 1)
            keys = self._get_keys_for_backend(backend)
            
            for key_name, key_value in keys:
                attempts.append(FailoverAttempt(backend, model, key_name, key_value))
        
        return attempts
    
    def _get_attempts_round_robin_keys(self, elements: list[str]) -> list[FailoverAttempt]:
        """Get failover attempts for round-robin keys across models.
        
        Args:
            elements: List of backend:model elements
            
        Returns:
            List of failover attempts
        """
        attempts = []
        backends_used = set()
        key_map: dict[str, list[tuple[str, str]]] = {}
        
        # Collect backends and keys
        for element in elements:
            if ":" not in element:
                logger.warning(f"Invalid element format: {element}")
                continue
            
            backend, _ = element.split(":", 1)
            backends_used.add(backend)
        
        # Get keys for each backend
        for backend in backends_used:
            key_map[backend] = self._get_keys_for_backend(backend)
        
        # Find the maximum number of keys
        max_keys = max((len(keys) for keys in key_map.values()), default=0)
        
        # Build attempts in round-robin fashion
        for i in range(max_keys):
            for element in elements:
                if ":" not in element:
                    continue
                
                backend, model = element.split(":", 1)
                
                if i < len(key_map.get(backend, [])):
                    key_name, key_value = key_map[backend][i]
                    attempts.append(FailoverAttempt(backend, model, key_name, key_value))
        
        return attempts
