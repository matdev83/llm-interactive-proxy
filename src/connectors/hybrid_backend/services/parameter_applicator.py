"""ParameterApplicator service for applying phase-specific parameters.

This service extracts parameter application logic from HybridConnector to provide
focused, testable components for applying reasoning and execution phase parameters.

Requirements satisfied:
- Req 2.2: ParameterApplicator extraction
- Req 3: Protocol-first design
"""

import logging
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.interfaces.model_bases import DomainModel, InternalDTO

from src.connectors.utils.model_capabilities import (
    get_execution_params,
    get_reasoning_params,
)
from src.core.interfaces.model_bases import DomainModel, InternalDTO

logger = logging.getLogger(__name__)


class ParameterApplicator:
    """Service for applying phase-specific parameters to request data.

    Handles applying reasoning and execution phase parameters to various
    request data types (Pydantic models, dicts, dataclasses).
    """

    def _apply_parameter_overrides(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        params: dict[str, Any],
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply a parameter dictionary to the request data."""
        # Coerce to a plain dict so callers may pass BackendParameters (or other
        # dict()-compatible objects). Empty BackendParameters must map to {} — the
        # model instance is always truthy and would otherwise skip this early return
        # and still mutate dict payloads (e.g. inject extra_body=None).
        plain_params: dict[str, Any] = dict(params)
        if not plain_params:
            return request_data

        # Log the overrides
        for key, value in plain_params.items():
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Applying override %s=%s to request", key, value)

        # Handle Pydantic models (includes CanonicalChatRequest)
        if isinstance(request_data, DomainModel):
            # Ensure extra_body is a mutable dict
            current_extra_body = getattr(request_data, "extra_body", None)
            new_extra_body = dict(current_extra_body) if current_extra_body else {}

            # Apply overrides
            new_extra_body.update(plain_params)

            # Strip hybrid routing hints that would confuse downstream connectors
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)

            return request_data.model_copy(
                update={
                    "extra_body": new_extra_body if new_extra_body else None,
                    **plain_params,
                }
            )

        # Handle dicts
        elif isinstance(request_data, dict):
            request_copy = dict(request_data)
            # Ensure extra_body exists and is a mutable dict
            current_extra_body = request_copy.get("extra_body")
            new_extra_body = (
                dict(current_extra_body) if isinstance(current_extra_body, dict) else {}
            )

            # Apply overrides
            new_extra_body.update(plain_params)
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)
            request_copy["extra_body"] = new_extra_body if new_extra_body else None

            # Expose overrides at the top level for compatibility
            request_copy.update(plain_params)

            return request_copy

        # Handle dataclasses
        elif is_dataclass(request_data) and not isinstance(request_data, type):
            request_dict = asdict(request_data)
            # Ensure extra_body exists and is a mutable dict
            current_extra_body = request_dict.get("extra_body")
            new_extra_body = (
                dict(current_extra_body) if isinstance(current_extra_body, dict) else {}
            )

            # Apply overrides
            new_extra_body.update(plain_params)
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)
            request_dict["extra_body"] = new_extra_body if new_extra_body else None

            # Merge overrides into the dataclass representation
            request_dict.update(plain_params)

            # Return as dict since we can't easily reconstruct the dataclass
            return request_dict
        # Fallback: return original if type is not supported
        logger.warning(
            "Unsupported request_data type in _apply_parameter_overrides: %s",
            type(request_data).__name__,
        )
        return request_data

    def apply_reasoning_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend: str,
        params: dict[str, Any] | None = None,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply reasoning-phase parameters to request data.

        Args:
            request_data: Request data in various formats (Pydantic model, dict, etc.)
            backend: Backend name for parameter lookup
            params: Optional parameter overrides

        Returns:
            Modified request data with reasoning parameters applied
        """
        # Get base reasoning parameters for backend
        base_params = dict(get_reasoning_params(backend))

        # Merge with URI parameter overrides if provided
        if params:
            base_params.update(params)

        return self._apply_parameter_overrides(request_data, base_params)

    def apply_execution_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend: str,
        params: dict[str, Any] | None = None,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply execution-phase parameters to request data.

        Args:
            request_data: Request data in various formats (Pydantic model, dict, etc.)
            backend: Backend name for parameter lookup
            params: Optional parameter overrides

        Returns:
            Modified request data with execution parameters applied
        """
        # Get base execution parameters for backend
        base_params = dict(get_execution_params(backend))

        # Merge with URI parameter overrides if provided
        if params:
            base_params.update(params)

        return self._apply_parameter_overrides(request_data, base_params)
