"""Reasoning configuration applicator implementation.

Applies reasoning configuration from session to requests.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest

logger = logging.getLogger(__name__)


class ReasoningConfigApplicator(IReasoningConfigApplicator):
    """Service for applying reasoning configuration to requests."""

    def apply(self, request: ChatRequest, session: Any) -> ChatRequest:
        """Apply reasoning configuration from session to request.

        If `session.get_reasoning_mode()` returns None, request is unchanged.
        Numeric overrides respect edit-precision constraints.
        Prompt prefix/suffix is applied to user text in both string and multipart
        message content without altering non-text parts.
        """
        try:
            # Get reasoning configuration from session
            reasoning_config = getattr(session, "get_reasoning_mode", lambda: None)()
            if reasoning_config is None:
                return request

            # Collect field updates to avoid mutating frozen Pydantic models
            updates: dict[str, Any] = {}

            extra_body_attr = getattr(request, "extra_body", None)
            edit_precision_active = False
            if isinstance(extra_body_attr, dict):
                try:
                    edit_precision_active = bool(
                        extra_body_attr.get("_edit_precision_mode")
                    )
                except (TypeError, AttributeError) as e:
                    # Expected exceptions from type conversion or attribute access
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to parse _edit_precision_mode from extra_body, defaulting to False: %s",
                            e,
                            exc_info=True,
                        )
                    edit_precision_active = False
                except Exception as e:
                    # Unexpected exceptions should be logged at WARNING level
                    logger.warning(
                        "Unexpected error parsing _edit_precision_mode from extra_body: %s",
                        e,
                        exc_info=True,
                    )
                    edit_precision_active = False
            else:
                edit_precision_active = False

            def _apply_numeric_update(field: str, value: Any) -> None:
                # Helper to apply numeric overrides while respecting edit precision.
                if value is None:
                    return
                numeric_value: Any = value
                try:
                    if field in {"temperature", "top_p"}:
                        numeric_value = float(value)
                    elif field == "top_k":
                        numeric_value = int(value)
                except (TypeError, ValueError):
                    numeric_value = value

                if edit_precision_active and field in {"temperature", "top_p", "top_k"}:
                    current_value = getattr(request, field, None)
                    try:
                        if current_value is not None:
                            if field in {"temperature", "top_p"}:
                                numeric_value = min(
                                    float(current_value), float(numeric_value)
                                )
                            else:
                                numeric_value = min(
                                    int(current_value), int(numeric_value)
                                )
                    except (TypeError, ValueError) as e:
                        # Failed to apply edit precision constraint - use override value
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Failed to apply edit precision constraint for field '%s': %s",
                                field,
                                e,
                                exc_info=True,
                            )

                updates[field] = numeric_value

            # Apply temperature if set
            if (
                hasattr(reasoning_config, "temperature")
                and reasoning_config.temperature is not None
            ):
                _apply_numeric_update("temperature", reasoning_config.temperature)

            # Apply top_p if set (for OpenAI-compatible backends)
            if (
                hasattr(reasoning_config, "top_p")
                and reasoning_config.top_p is not None
            ):
                _apply_numeric_update("top_p", reasoning_config.top_p)

            if (
                hasattr(reasoning_config, "top_k")
                and reasoning_config.top_k is not None
            ):
                _apply_numeric_update("top_k", reasoning_config.top_k)

            # Apply reasoning_effort if set (for OpenAI reasoning models)
            if (
                hasattr(reasoning_config, "reasoning_effort")
                and reasoning_config.reasoning_effort is not None
            ):
                updates["reasoning_effort"] = reasoning_config.reasoning_effort

            # Apply thinking_budget if set (for Gemini models)
            if (
                hasattr(reasoning_config, "thinking_budget")
                and reasoning_config.thinking_budget is not None
            ):
                updates["thinking_budget"] = reasoning_config.thinking_budget

            # Apply reasoning_config if set
            if (
                hasattr(reasoning_config, "reasoning_config")
                and reasoning_config.reasoning_config is not None
            ):
                updates["reasoning"] = reasoning_config.reasoning_config

            # Apply gemini_generation_config if set
            if (
                hasattr(reasoning_config, "gemini_generation_config")
                and reasoning_config.gemini_generation_config is not None
            ):
                updates["generation_config"] = reasoning_config.gemini_generation_config

            # Apply planning-phase overrides if active
            try:
                planning_cfg = getattr(session.state, "planning_phase_config", None)
                if planning_cfg and bool(getattr(planning_cfg, "enabled", False)):
                    overrides = getattr(planning_cfg, "overrides", None)
                    if isinstance(overrides, dict):
                        if overrides.get("temperature") is not None:
                            _apply_numeric_update(
                                "temperature", overrides.get("temperature")
                            )
                        if overrides.get("top_p") is not None:
                            _apply_numeric_update("top_p", overrides.get("top_p"))
                        if overrides.get("top_k") is not None:
                            _apply_numeric_update("top_k", overrides.get("top_k"))
                        if overrides.get("reasoning_effort") is not None:
                            updates["reasoning_effort"] = overrides.get(
                                "reasoning_effort"
                            )
                        if overrides.get("thinking_budget") is not None:
                            updates["thinking_budget"] = overrides.get(
                                "thinking_budget"
                            )
                        if overrides.get("reasoning") is not None:
                            updates["reasoning"] = overrides.get("reasoning")
                        if overrides.get("generation_config") is not None:
                            updates["generation_config"] = overrides.get(
                                "generation_config"
                            )
            except (AttributeError, TypeError, KeyError) as e:
                # Expected exceptions from attribute access, type conversion, or dict access
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Planning-phase overrides application failed (expected error): %s",
                        e,
                        exc_info=True,
                    )
            except Exception as e:
                # Unexpected exceptions should be logged at WARNING level
                logger.warning(
                    "Unexpected error applying planning-phase overrides: %s",
                    e,
                    exc_info=True,
                )

            if updates:
                request = request.model_copy(update=updates)

            # Apply prompt prefix and suffix if available in reasoning config
            prefix = getattr(reasoning_config, "user_prompt_prefix", None)
            suffix = getattr(reasoning_config, "user_prompt_suffix", None)

            if (
                (
                    (prefix is not None and prefix != "")
                    or (suffix is not None and suffix != "")
                )
                and hasattr(request, "messages")
                and request.messages
            ):
                modified_messages = []
                for message in request.messages:
                    # Only modify user messages
                    if getattr(message, "role", "") == "user":
                        content = getattr(message, "content", None)
                        if isinstance(content, str):
                            new_content = ""
                            if prefix is not None:
                                new_content += prefix
                            new_content += content
                            if suffix is not None:
                                new_content += suffix
                            modified_message = message.model_copy(
                                update={"content": new_content}
                            )
                            modified_messages.append(modified_message)
                        elif isinstance(content, list):
                            # For multimodal content, modify the first text part
                            modified_content = []
                            for part in content:
                                if (
                                    hasattr(part, "type")
                                    and part.type == "text"
                                    and hasattr(part, "text")
                                ):
                                    new_text = ""
                                    if prefix is not None:
                                        new_text += prefix
                                    new_text += part.text
                                    if suffix is not None:
                                        new_text += suffix
                                    modified_part = part.model_copy(
                                        update={"text": new_text}
                                    )
                                    modified_content.append(modified_part)
                                else:
                                    modified_content.append(part)
                            # If no text part found, add prefix/suffix as new text
                            if not any(
                                hasattr(part, "type") and part.type == "text"
                                for part in content
                            ):
                                if prefix is not None:
                                    modified_content.insert(
                                        0, {"type": "text", "text": prefix}
                                    )
                                if suffix is not None:
                                    modified_content.append(
                                        {"type": "text", "text": suffix}
                                    )
                            modified_message = message.model_copy(
                                update={"content": modified_content}
                            )
                            modified_messages.append(modified_message)
                        else:
                            modified_messages.append(message)
                    else:
                        modified_messages.append(message)
                # Update the request with modified messages
                request = request.model_copy(update={"messages": modified_messages})

        except (AttributeError, TypeError, ValueError, ValidationError, KeyError) as e:
            # Expected exceptions from attribute access, type conversion, parsing, or model validation
            # Log at DEBUG level and continue (fail-open behavior)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to apply reasoning config (expected error): %s",
                    e,
                    exc_info=True,
                )
        except Exception as e:
            # Unexpected exceptions should be logged at WARNING level for visibility
            logger.warning(
                "Unexpected error while applying reasoning config: %s", e, exc_info=True
            )

        return request
