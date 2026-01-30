"""
Backend preparer implementation.

This module provides backend request preparation and validation,
extracted from RequestProcessor during refactoring.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import ChatRequest
from src.core.domain.model_utils import ModelDefaults, parse_model_backend
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.interfaces.request_processor_internal import IBackendPreparer
from src.core.utils.token_count import count_tokens, extract_prompt_text

if TYPE_CHECKING:
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.backend_request_manager_interface import (
        IBackendRequestManager,
    )
    from src.core.services.model_catalog_service import ModelCatalogService


logger = logging.getLogger(__name__)


def _extract_required_input_modalities(request: ChatRequest | None) -> set[str]:
    required: set[str] = {"text"}
    if request is None:
        return required

    for message in request.messages:
        content = getattr(message, "content", None)
        parts: list[Any] = []
        if isinstance(content, list | tuple):
            parts = list(content)
        elif isinstance(content, dict):
            parts = [content]

        for part in parts:
            part_type = getattr(part, "type", None)
            if part_type is None and isinstance(part, dict):
                part_type = part.get("type")
            if part_type == "image_url":
                required.add("image")
            elif part_type == "input_audio":
                required.add("audio")

    return required


class BackendPreparer(IBackendPreparer):
    """
    Handles backend request preparation and validation.

    This component extracts backend preparation logic from RequestProcessor,
    including:
    - Backend request creation via BackendRequestManager
    - Token limit enforcement (input and total tokens)
    - Model defaults lookup with CLI override support
    - Structured InvalidRequestError for validation failures
    - Fail-open behavior for unexpected errors
    """

    _model_catalog: ModelCatalogService | None

    def __init__(
        self,
        backend_request_manager: IBackendRequestManager,
        app_state: IApplicationState | None = None,
        model_catalog: ModelCatalogService | None = None,
    ) -> None:
        """
        Initialize the backend preparer.

        Args:
            backend_request_manager: Service for preparing backend requests
            app_state: Optional application state for configuration access
            model_catalog: Optional model catalog for metadata lookups
        """
        self._backend_request_manager = backend_request_manager
        self._app_state = app_state
        self._model_catalog: ModelCatalogService | None = model_catalog

    async def prepare(
        self,
        context: RequestContext,
        session_id: str,
        request: ChatRequest,
        processed: ProcessedResult,
    ) -> ChatRequest | None:
        """
        Prepare backend request and enforce validation limits.

        Returns:
            - ChatRequest: Prepared backend request ready for transformations
            - None: Backend should be skipped (e.g., command-only flow)

        This method handles:
        - Backend request preparation via BackendRequestManager
        - Token limit enforcement (fail-fast on structured validation)
        - Context window validation

        Raises:
            InvalidRequestError: When structured validation fails (input/total token limits)
        """
        # Prepare backend request
        backend_request = await self._backend_request_manager.prepare_backend_request(
            request, processed
        )

        # Enforce per-model context window limits (front-end enforcement)
        if backend_request is not None and self._app_state is not None:
            try:
                # Check if model limit enforcement is enabled
                enforcement_enabled = True
                try:
                    app_config = self._app_state.get_setting("app_config")
                    if app_config is not None:
                        # Handle both object and dict-like config
                        enforcement_cfg = getattr(
                            app_config, "model_limit_enforcement", None
                        )
                        if enforcement_cfg is not None:
                            enforcement_enabled = getattr(
                                enforcement_cfg, "enabled", True
                            )
                except (AttributeError, KeyError, TypeError):
                    enforcement_enabled = True

                if not enforcement_enabled:
                    return backend_request

                model_defaults_map: dict[str, ModelDefaults] = (
                    self._app_state.get_model_defaults() or {}
                )

                # Resolve backend and model name
                backend_type: str | None = None
                try:
                    backend_type = self._app_state.get_backend_type()
                except (AttributeError, RuntimeError, TypeError) as err:
                    # AttributeError: app_state missing get_backend_type
                    # RuntimeError: threading lock issues or state corruption
                    # TypeError: app_state is None or wrong type
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to get backend type from app_state: %s",
                            type(err).__name__,
                            exc_info=True,
                        )
                    backend_type = None

                _rm = getattr(backend_request, "model", None) or getattr(
                    request, "model", ""
                )
                requested_model: str = str(_rm)
                parsed = parse_model_backend(requested_model, (backend_type or ""))
                backend_key: str = parsed.backend_type
                model_name: str = parsed.model_name

                model_catalog = self._model_catalog

                # If registry data is unavailable or model is missing, skip enforcement
                if model_catalog is None:
                    return backend_request

                if not model_catalog.has_model(model_name, backend_key):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Skipping limit/modality enforcement: model not found in registry (%s)",
                            requested_model,
                        )
                    return backend_request

                # Candidate keys to look up defaults
                candidate_keys: list[str] = []
                if requested_model:
                    candidate_keys.append(requested_model)
                if backend_key and model_name:
                    candidate_keys.append(f"{backend_key}:{model_name}")
                    candidate_keys.append(f"{backend_key}/{model_name}")
                if model_name:
                    candidate_keys.append(model_name)

                model_defaults: ModelDefaults | dict[str, Any] | None = None
                for k in candidate_keys:
                    md: Any = model_defaults_map.get(k)
                    if md is None:
                        continue
                    # Accept either a ModelDefaults instance or a plain dict-like
                    if isinstance(md, dict) or hasattr(md, "limits"):
                        model_defaults = md
                        break

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Model limits lookup: requested_model=%s backend=%s model=%s candidates=%s found=%s",
                        requested_model,
                        backend_key,
                        model_name,
                        candidate_keys,
                        bool(model_defaults),
                    )

                # Enforce input modality support when catalog data is available
                input_modalities = model_catalog.get_input_modalities(
                    model_name, backend_key
                )
                if isinstance(input_modalities, set) and input_modalities:
                    required_modalities = _extract_required_input_modalities(
                        backend_request
                    )
                    missing_modalities = required_modalities - input_modalities
                    if missing_modalities:
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Unsupported input modalities: required=%s supported=%s missing=%s model=%s",
                                sorted(required_modalities),
                                sorted(input_modalities),
                                sorted(missing_modalities),
                                requested_model,
                            )
                        raise InvalidRequestError(
                            message=(
                                "Model does not support required input modalities"
                            ),
                            code="unsupported_modality",
                            param="messages",
                            details={
                                "model": requested_model or model_name,
                                "required": sorted(required_modalities),
                                "supported": sorted(input_modalities),
                                "missing": sorted(missing_modalities),
                            },
                        )

                # Check for CLI context window override first
                cli_context_window = None
                app_state = self._app_state
                if app_state is not None:  # type: ignore[truthy-function]
                    try:
                        app_config = app_state.get_setting("app_config")
                        if app_config is not None and hasattr(
                            app_config, "context_window_override"
                        ):
                            cli_context_window = getattr(
                                app_config, "context_window_override", None
                            )
                    except (AttributeError, KeyError, TypeError):
                        cli_context_window = None

                limits = (
                    getattr(model_defaults, "limits", None)
                    if model_defaults is not None
                    and not isinstance(model_defaults, dict)
                    else (
                        model_defaults.get("limits")
                        if isinstance(model_defaults, dict)
                        else None
                    )
                )

                # Try to get limits from model catalog if not found in model_defaults
                if limits is None:
                    catalog_limits = model_catalog.get_limits(model_name, backend_key)
                    if catalog_limits:
                        limits = catalog_limits
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Found limits for %s in model catalog", model_name
                            )

                # Apply CLI override if set

                if cli_context_window is not None and cli_context_window > 0:
                    # Create a new limits object or modify existing to use CLI override
                    if limits is None:
                        limits = {"context_window": cli_context_window}
                    elif isinstance(limits, dict):
                        limits = limits.copy()
                        limits["context_window"] = cli_context_window
                        # Also update max_input_tokens to match for consistency
                        limits["max_input_tokens"] = cli_context_window
                    else:
                        # Create a dict representation for object-based limits
                        limits = {
                            "context_window": cli_context_window,
                            "max_input_tokens": cli_context_window,
                            "max_output_tokens": getattr(
                                limits, "max_output_tokens", None
                            ),
                            "requests_per_minute": getattr(
                                limits, "requests_per_minute", None
                            ),
                            "tokens_per_minute": getattr(
                                limits, "tokens_per_minute", None
                            ),
                        }

                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applied CLI context window override: %s tokens for model %s",
                            cli_context_window,
                            requested_model or model_name,
                        )
                if limits is not None:
                    # Enforce input token limit as a hard error
                    try:
                        # Determine effective input token limit. Prefer explicit max_input_tokens,
                        # but fall back to context_window when only that is configured.
                        max_in = None
                        context_window = None
                        if isinstance(limits, dict):
                            max_in = limits.get("max_input_tokens") or limits.get(
                                "context_window"
                            )
                            context_window = limits.get("context_window")
                        else:
                            max_in = getattr(
                                limits, "max_input_tokens", None
                            ) or getattr(limits, "context_window", None)
                            context_window = getattr(limits, "context_window", None)

                        if max_in is not None and max_in > 0:
                            text = extract_prompt_text(
                                getattr(backend_request, "messages", []) or []
                            )
                            measured = int(count_tokens(text, model=model_name))

                            # Check input token limit
                            if measured > int(max_in):
                                if logger.isEnabledFor(logging.INFO):
                                    logger.info(
                                        "Input token limit exceeded: measured=%s limit=%s model=%s",
                                        measured,
                                        int(max_in),
                                        requested_model,
                                    )
                                raise InvalidRequestError(
                                    message="Input token limit exceeded",
                                    code="input_limit_exceeded",
                                    param="messages",
                                    details={
                                        "model": requested_model or model_name,
                                        "limit": int(max_in),
                                        "measured": measured,
                                    },
                                )

                            # Check total token limit (input + max_tokens) against context window
                            max_tokens = getattr(backend_request, "max_tokens", None)

                            # Determine effective max output tokens for safety check
                            # (what the model is capable of outputting)
                            max_out_limit = None
                            if isinstance(limits, dict):
                                max_out_limit = limits.get("max_output_tokens")
                            else:
                                max_out_limit = getattr(
                                    limits, "max_output_tokens", None
                                )

                            if context_window is not None and context_window > 0:
                                # 1. Check against explicitly requested max_tokens
                                if max_tokens is not None and max_tokens > 0:
                                    total_requested = measured + max_tokens
                                    if total_requested > context_window:
                                        if logger.isEnabledFor(logging.INFO):
                                            logger.info(
                                                "Total token limit exceeded: input=%s + max_tokens=%s = %s > context_window=%s model=%s",
                                                measured,
                                                max_tokens,
                                                total_requested,
                                                context_window,
                                                requested_model,
                                            )
                                        raise InvalidRequestError(
                                            message="Total token limit exceeded (input + max_tokens exceeds context window)",
                                            code="total_limit_exceeded",
                                            param="max_tokens",
                                            details={
                                                "model": requested_model or model_name,
                                                "context_window": int(context_window),
                                                "input_tokens": measured,
                                                "max_tokens": max_tokens,
                                                "total_requested": total_requested,
                                                "suggestion": f"Reduce max_tokens to {context_window - measured} or less",
                                            },
                                        )

                                # 2. Check if input is so large that model's intrinsic max output cannot fit
                                if (
                                    max_out_limit is not None
                                    and max_out_limit > 0
                                    and max_out_limit < context_window
                                    and measured + max_out_limit > context_window
                                ):
                                    if logger.isEnabledFor(logging.INFO):
                                        logger.info(
                                            "Model capacity exceeded: input=%s + model_max_output=%s = %s > context_window=%s model=%s",
                                            measured,
                                            max_out_limit,
                                            measured + max_out_limit,
                                            context_window,
                                            requested_model,
                                        )
                                    raise InvalidRequestError(
                                        message="Model capacity exceeded: input size leaves no room for maximum model output",
                                        code="model_capacity_exceeded",
                                        param="messages",
                                        details={
                                            "model": requested_model or model_name,
                                            "context_window": int(context_window),
                                            "input_tokens": measured,
                                            "model_max_output": max_out_limit,
                                            "total_required": measured + max_out_limit,
                                            "available_for_output": max(
                                                0, context_window - measured
                                            ),
                                        },
                                    )

                    except InvalidRequestError:
                        # Re-raise structured invalid request
                        raise
                    except (
                        ValueError,
                        TypeError,
                        AttributeError,
                        KeyError,
                        RuntimeError,
                    ):
                        # Unexpected error during enforcement: fail-open
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Failed to enforce input token limit; continuing",
                                exc_info=True,
                            )
            except InvalidRequestError:
                # Bubble up to FastAPI exception handlers
                raise
            except (ValueError, TypeError, AttributeError, KeyError, RuntimeError):
                # Unexpected error in validation setup: fail-open
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to set up token validation; continuing", exc_info=True
                    )

        return backend_request
