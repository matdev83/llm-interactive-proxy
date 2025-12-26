"""
Assessment prompts for LLM-based conversation assessment.

This module provides access to assessment prompts loaded from Markdown files,
avoiding hardcoded prompts in Python code.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts (lines 61-75)
"""

import logging
from typing import Any

from src.core.common.logging_utils import get_logger, is_log_level_enabled
from src.core.services.assessment_prompt_loader import (
    AssessmentPromptLoader,
    PromptInfo,
)

logger = get_logger(__name__)

# Global prompt loader instance
_prompt_loader: AssessmentPromptLoader | None = None


def get_prompt_loader() -> AssessmentPromptLoader:
    """
    Get the global prompt loader instance.

    Returns:
        AssessmentPromptLoader instance
    """
    global _prompt_loader
    if _prompt_loader is None:
        _prompt_loader = AssessmentPromptLoader()
    return _prompt_loader


def initialize_prompts() -> None:
    """
    Initialize assessment prompts by loading them from files.

    This should be called once at application startup when assessment is enabled.

    Raises:
        FileNotFoundError: If prompt files are missing
        ValueError: If prompt files are invalid
    """
    loader = get_prompt_loader()
    if not loader.is_loaded:
        loader.load_prompts()
        logger.info("Assessment prompts initialized successfully")
    else:
        if is_log_level_enabled(logger, logging.DEBUG):
            logger.debug("Assessment prompts already initialized")


def get_system_prompt() -> str:
    """
    Get the system prompt for assessment.

    Returns:
        System prompt text loaded from system_prompt.md

    Raises:
        RuntimeError: If prompts haven't been initialized
    """
    loader = get_prompt_loader()
    return loader.system_prompt


def get_task_prompt() -> str:
    """
    Get the task prompt for assessment.

    Returns:
        Task prompt text loaded from task_prompt.md

    Raises:
        RuntimeError: If prompts haven't been initialized
    """
    loader = get_prompt_loader()
    return loader.task_prompt


def get_response_schema() -> dict[str, Any]:
    """
    Get the response schema for assessment.

    Returns:
        Response schema loaded from response_schema.json

    Raises:
        RuntimeError: If prompts haven't been initialized
    """
    loader = get_prompt_loader()
    return loader.response_schema


def get_steering_template() -> str:
    """
    Get the steering message template for assessment.

    Returns:
        Steering message template loaded from steering_message_template.md

    Raises:
        RuntimeError: If prompts haven't been initialized
    """
    loader = get_prompt_loader()
    return loader.steering_template


def is_initialized() -> bool:
    """
    Check if assessment prompts have been initialized.

    Returns:
        True if prompts are loaded and ready to use
    """
    loader = get_prompt_loader()
    return loader.is_loaded


def get_prompt_info() -> PromptInfo:
    """
    Get information about loaded prompts.

    Returns:
        PromptInfo with loading status and metadata
    """
    loader = get_prompt_loader()
    return loader.get_prompt_info()


# Legacy constants for backward compatibility (deprecated)
# These will be removed in a future version
def _get_legacy_constants():
    """Get legacy constants for backward compatibility."""
    if not is_initialized():
        # Return empty strings if not initialized to avoid breaking existing code
        logger.warning(
            "Assessment prompts not initialized, returning empty legacy constants"
        )
        return "", "", {}

    return get_system_prompt(), get_task_prompt(), get_response_schema()


# Deprecated: Use get_system_prompt() instead
ASSESSMENT_SYSTEM_PROMPT = ""

# Deprecated: Use get_task_prompt() instead
ASSESSMENT_TASK_PROMPT = ""

# Deprecated: Use get_response_schema() instead
ASSESSMENT_RESPONSE_SCHEMA: dict[str, Any] = {}
