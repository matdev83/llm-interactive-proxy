"""
Assessment prompt loader service.

This service loads assessment prompts from Markdown files at startup,
avoiding hardcoded prompts in Python code and preventing repeated file I/O.
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.core.common.logging_utils import get_logger

logger = get_logger(__name__)


class PromptInfo(BaseModel):
    """Information about loaded assessment prompts.

    Provides a strongly-typed contract for prompt metadata
    including loading status, file locations, and content lengths.
    """

    loaded: bool
    prompts_dir: str | None = None
    system_prompt_length: int = 0
    task_prompt_length: int = 0
    steering_template_length: int = 0
    schema_properties: list[str] = []

    model_config = {"extra": "forbid"}


# Fallback hardcoded prompts (used when files are missing)
FALLBACK_SYSTEM_PROMPT = """You are a sophisticated AI diagnostic agent specializing in identifying when a conversational AI is stuck in an unproductive state. Your task is to analyze the provided conversation history and determine if the assistant has ceased to make meaningful progress.

An unproductive state is characterized by one or more of the following patterns over the last 5 or more assistant turns:

Repetitive Actions: The assistant repeats the same tool calls or conversational responses a decent number of times. This includes simple loops (e.g., tool_A, tool_A, tool_A) and alternating patterns (e.g., tool_A, tool_B, tool_A, tool_B, ...).

Cognitive Loop: The assistant seems unable to determine the next logical step. It might express confusion, repeatedly ask the same questions, or generate responses that don't logically follow from the previous turns, indicating it's stuck and not advancing the task.

Crucially, differentiate between a true unproductive state and legitimate, incremental progress.
For example, a series of 'tool_A' or 'tool_B' tool calls that make small, distinct changes to the same file (like adding docstrings to functions one by one) is considered forward progress and is NOT a loop. A loop would be repeatedly replacing the same text with the same content, or cycling between a small set of files with no net change."""

FALLBACK_TASK_PROMPT = "Please analyze the conversation history to determine the possibility that the conversation is stuck in a repetitive, non-productive state. Provide your response in the requested JSON format."

FALLBACK_STEERING_TEMPLATE = (
    "[SYSTEM NOTICE] Potential conversation loop detected. {reasoning}"
)

FALLBACK_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "Your reasoning on if the conversation is looping without forward progress.",
        },
        "confidence": {
            "type": "number",
            "description": "A number between 0.0 and 1.0 representing your confidence that the conversation is in an unproductive state.",
        },
    },
    "required": ["reasoning", "confidence"],
}


class AssessmentPromptLoader:
    """
    Service for loading and caching assessment prompts from files.

    Prompts are loaded once at startup and cached in memory to avoid
    repeated file I/O operations during assessment requests.
    """

    def __init__(self, prompts_dir: str | None = None):
        """
        Initialize prompt loader.

        Args:
            prompts_dir: Directory containing prompt files. If None, uses default.
        """
        if prompts_dir is None:
            # Default to config/prompts/loop_assessment_prompts/
            self.prompts_dir = Path("config/prompts/loop_assessment_prompts")
        else:
            self.prompts_dir = Path(prompts_dir)

        self._system_prompt: str | None = None
        self._task_prompt: str | None = None
        self._response_schema: dict[str, Any] | None = None
        self._steering_template: str | None = None
        self._loaded = False

    def load_prompts(self) -> None:
        """
        Load all assessment prompts from files with fallback to hardcoded defaults.

        This method should be called once at startup to preload all prompts.
        If files are missing, corrupted, or inaccessible, it falls back to
        hardcoded defaults and logs appropriate warnings.
        """
        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Loading assessment prompts from %s", self.prompts_dir)

            # Load system prompt with fallback
            system_prompt_path = self.prompts_dir / "system_prompt.md"
            if system_prompt_path.exists():
                try:
                    with open(system_prompt_path, encoding="utf-8") as f:
                        self._system_prompt = f.read().strip()

                    if not self._system_prompt:
                        logger.warning("System prompt file is empty")
                        logger.warning(
                            "Using fallback system prompt (hardcoded default)"
                        )
                        self._system_prompt = FALLBACK_SYSTEM_PROMPT
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to read system prompt file: %s", e, exc_info=True
                        )
                    logger.warning(
                        "Using fallback system prompt (hardcoded default)", exc_info=True
                    )
                    self._system_prompt = FALLBACK_SYSTEM_PROMPT
            else:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "System prompt file not found: %s", system_prompt_path
                    )
                logger.warning("Using fallback system prompt (hardcoded default)")
                self._system_prompt = FALLBACK_SYSTEM_PROMPT

            # Load task prompt with fallback
            task_prompt_path = self.prompts_dir / "task_prompt.md"
            if task_prompt_path.exists():
                try:
                    with open(task_prompt_path, encoding="utf-8") as f:
                        self._task_prompt = f.read().strip()

                    if not self._task_prompt:
                        logger.warning("Task prompt file is empty")
                        logger.warning("Using fallback task prompt (hardcoded default)")
                        self._task_prompt = FALLBACK_TASK_PROMPT
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to read task prompt file: %s", e, exc_info=True
                        )
                    logger.warning("Using fallback task prompt (hardcoded default)")
                    self._task_prompt = FALLBACK_TASK_PROMPT
            else:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Task prompt file not found: %s", task_prompt_path)
                logger.warning("Using fallback task prompt (hardcoded default)")
                self._task_prompt = FALLBACK_TASK_PROMPT

            # Load response schema with fallback
            schema_path = self.prompts_dir / "response_schema.json"
            if schema_path.exists():
                try:
                    with open(schema_path, encoding="utf-8") as f:
                        self._response_schema = json.load(f)

                    if not self._response_schema:
                        logger.warning("Response schema file is empty")
                        logger.warning(
                            "Using fallback response schema (hardcoded default)"
                        )
                        self._response_schema = FALLBACK_RESPONSE_SCHEMA
                    else:
                        # Validate schema structure
                        if not isinstance(self._response_schema, dict):
                            logger.warning("Response schema is not a JSON object")
                            logger.warning(
                                "Using fallback response schema (hardcoded default)"
                            )
                            self._response_schema = FALLBACK_RESPONSE_SCHEMA
                        elif "properties" not in self._response_schema:
                            logger.warning("Response schema missing 'properties' field")
                            logger.warning(
                                "Using fallback response schema (hardcoded default)"
                            )
                            self._response_schema = FALLBACK_RESPONSE_SCHEMA
                        else:
                            # Check required properties
                            required_properties = ["reasoning", "confidence"]
                            schema_properties = self._response_schema.get(
                                "properties", {}
                            )

                            missing_props = [
                                prop
                                for prop in required_properties
                                if prop not in schema_properties
                            ]
                            if missing_props:
                                logger.warning(
                                    f"Response schema missing required properties {missing_props}"
                                )
                                logger.warning(
                                    "Using fallback response schema (hardcoded default)"
                                )
                                self._response_schema = FALLBACK_RESPONSE_SCHEMA
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to read response schema file: %s", e, exc_info=True
                        )
                    logger.warning("Using fallback response schema (hardcoded default)")
                    self._response_schema = FALLBACK_RESPONSE_SCHEMA
            else:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Response schema file not found: %s", schema_path)
                logger.warning("Using fallback response schema (hardcoded default)")
                self._response_schema = FALLBACK_RESPONSE_SCHEMA

            # Load steering message template with fallback
            steering_template_path = self.prompts_dir / "steering_message_template.md"
            if steering_template_path.exists():
                try:
                    with open(steering_template_path, encoding="utf-8") as f:
                        self._steering_template = f.read().strip()

                    if not self._steering_template:
                        logger.warning("Steering message template file is empty")
                        logger.warning(
                            "Using fallback steering template (hardcoded default)"
                        )
                        self._steering_template = FALLBACK_STEERING_TEMPLATE
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to read steering message template file: %s",
                            e,
                            exc_info=True,
                        )
                    logger.warning(
                        "Using fallback steering template (hardcoded default)"
                    )
                    self._steering_template = FALLBACK_STEERING_TEMPLATE
            else:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Steering message template file not found: %s",
                        steering_template_path,
                    )
                logger.warning("Using fallback steering template (hardcoded default)")
                self._steering_template = FALLBACK_STEERING_TEMPLATE

            self._loaded = True

            schema_properties = self._response_schema.get("properties", {})
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Successfully loaded assessment prompts: "
                    "system_prompt=%d chars, "
                    "task_prompt=%d chars, "
                    "steering_template=%d chars, "
                    "schema_properties=%d",
                    len(self._system_prompt),
                    len(self._task_prompt),
                    len(self._steering_template),
                    len(schema_properties),
                )

        except Exception as e:
            logger.error(f"Failed to load assessment prompts: {e}", exc_info=True)
            raise

    @property
    def system_prompt(self) -> str:
        """
        Get the system prompt for assessment.

        Returns:
            System prompt text

        Raises:
            RuntimeError: If prompts haven't been loaded yet
        """
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._system_prompt is None:
            raise RuntimeError("System prompt not available.")
        return self._system_prompt

    @property
    def task_prompt(self) -> str:
        """
        Get the task prompt for assessment.

        Returns:
            Task prompt text

        Raises:
            RuntimeError: If prompts haven't been loaded yet
        """
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._task_prompt is None:
            raise RuntimeError("Task prompt not available.")
        return self._task_prompt

    @property
    def response_schema(self) -> dict[str, Any]:
        """
        Get the response schema for assessment.

        Returns:
            Response schema as dictionary

        Raises:
            RuntimeError: If prompts haven't been loaded yet
        """
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._response_schema is None:
            raise RuntimeError("Response schema not available.")
        return self._response_schema

    @property
    def steering_template(self) -> str:
        """
        Get the steering message template for assessment.

        Returns:
            Steering message template loaded from steering_message_template.md

        Raises:
            RuntimeError: If prompts haven't been loaded yet
        """
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._steering_template is None:
            raise RuntimeError("Steering template not available.")
        return self._steering_template

    @property
    def is_loaded(self) -> bool:
        """Check if prompts have been loaded."""
        return self._loaded

    def reload_prompts(self) -> None:
        """
        Reload prompts from files.

        This can be used to refresh prompts without restarting the application.
        """
        self._loaded = False
        self.load_prompts()

    def get_prompt_info(self) -> PromptInfo:
        """
        Get information about loaded prompts.

        Returns:
            PromptInfo with loading status and metadata
        """
        if not self._loaded:
            return PromptInfo(loaded=False)

        return PromptInfo(
            loaded=True,
            prompts_dir=str(self.prompts_dir),
            system_prompt_length=len(self._system_prompt or ""),
            task_prompt_length=len(self._task_prompt or ""),
            steering_template_length=len(self._steering_template or ""),
            schema_properties=list(
                (self._response_schema or {}).get("properties", {}).keys()
            ),
        )
