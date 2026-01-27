"""
Angel prompt loader service.

This service loads Angel prompts from Markdown files at startup,
avoiding hardcoded prompts in Python code and preventing repeated file I/O.
"""

from pathlib import Path

from pydantic import BaseModel

from src.core.common.logging_utils import get_logger

logger = get_logger(__name__)


class AngelPromptInfo(BaseModel):
    """Information about loaded Angel prompts.

    Provides a strongly-typed contract for Angel prompt metadata
    including loading status, file locations, and content lengths.
    """

    loaded: bool
    prompts_dir: str | None = None
    angel_prompt_length: int = 0
    steering_template_length: int = 0

    model_config = {"extra": "forbid"}


# Fallback hardcoded prompts (used when files are missing)
FALLBACK_ANGEL_PROMPT = (
    "You are `Angel`, an autonomous Quality Assurance Auditor. You sit at a proxy level between a Main Assistant and a User. \\n"
    "The last message in the provided conversation history is a **DRAFT response** from the Main Assistant. It has NOT been seen by the user yet. \\n"
    "Your mission: Audit this draft for technical errors, logic failures, or stagnation.\\n\\n"
    "### Auditing Rules:\\n"
    "1. **Be Conservative**: Only steer if there is a CLEAR error, logical failure, or obvious laziness. Avoid nitpicking style, wording, or harmless preferences if the technical content is correct and functional.\\n"
    "2. **Detect \"Soft\" Failures**: Look for \"I can't do that\" when the assistant actually HAS the tools to do it, or \"Code goes here...\" placeholders.\\n"
    "3. **Logic & Truthfulness**: Flag code that won't run as intended or reasoning that contradicts the user's requirements or the previously discovered state.\\n\\n"
    "### Decision Protocol:\\n"
    "- If the response is acceptable: Output ONLY \u003cangels_decision\u003ePass\u003c/angels_decision\u003e.\\n"
    "- If a correction is needed:\\n"
    "    1. Provide a brief internal reasoning for your audit.\\n"
    "    2. Output \u003cangels_decision\u003eSteer\u003c/angels_decision\u003e.\\n"
    "    3. Provide actionable, technical feedback in \u003cangels_steering_message\u003e...\u003c/angels_steering_message\u003e.\\n\\n"
    "### Specific Patterns to Flag:\\n"
    "- **Logical Failures**: The code or reasoning doesn't actually solve the user's specific problem.\\n"
    "- **Stagnation**: Making no progress over 10 user-assistant interaction turns (excluding tool result exchanges).\\n"
    "- **Confusion**: Assistant is hallucinating file structures, tool capabilities, or project state.\\n"
    "- **Laziness**: Using placeholders, truncating code arbitrarily, or refusing a task it has the capability to perform.\\n"
    "- **Garbage Output**: Malfunctioning output, mixed languages, or excessive repetition.\\n\\n"
    "Respect the format: Generate ONLY the brief internal reasoning followed by the structured XML tags. \\n"
    "You MUST NOT call any tools. You will receive no follow-backs or extra turns; you must generate your final audit decision now, in this current turn."
)

FALLBACK_STEERING_TEMPLATE = (
    "Hi there. I am an automated verification system monitoring this session to ensure quality and prevent errors. \\n"
    "I have intercepted your latest response because a potential issue was detected. To improve the user experience, I have temporarily blocked your previous output from reaching the client. \\n"
    "The detected problem is as follows:\\n"
    "\u003cdetected_problem\u003e\\n{angels_steering_message}\\n\u003c/detected_problem\u003e\\n"
    "Please re-generate and submit a corrected message. Your new output will be verified and, if approved, sent to the client. Just generate the corrected output, including any necessary tool calls. \\n"
    "Remember: I am an automated observer and cannot engage in discussion. I will only handle your next reply according to these rules."
)


class AngelPromptLoader:
    """
    Service for loading and caching Angel prompts from files.

    Prompts are loaded once at startup and cached in memory to avoid
    repeated file I/O operations during angel verification requests.
    """

    def __init__(self, prompts_dir: str | None = None):
        """
        Initialize prompt loader.

        Args:
            prompts_dir: Directory containing prompt files. If None, uses default.
        """
        if prompts_dir is None:
            # Default to config/prompts/angel_prompts/
            self.prompts_dir = Path("config/prompts/angel_prompts")
        else:
            self.prompts_dir = Path(prompts_dir)

        self._angel_prompt: str | None = None
        self._steering_template: str | None = None
        self._loaded = False

    def load_prompts(self) -> None:
        """
        Load all Angel prompts from files with fallback to hardcoded defaults.

        This method should be called once at startup to preload all prompts.
        If files are missing, corrupted, or inaccessible, it falls back to
        hardcoded defaults and logs appropriate warnings.
        """
        try:
            logger.info("Loading Angel prompts from %s", self.prompts_dir)

            # Load angel prompt with fallback
            angel_prompt_path = self.prompts_dir / "angel_prompt.md"
            if angel_prompt_path.exists():
                try:
                    with open(angel_prompt_path, encoding="utf-8") as f:
                        self._angel_prompt = f.read().strip()

                    if not self._angel_prompt:
                        logger.warning("Angel prompt file is empty")
                        logger.warning(
                            "Using fallback Angel prompt (hardcoded default)"
                        )
                        self._angel_prompt = FALLBACK_ANGEL_PROMPT
                except Exception as e:
                    logger.warning(
                        "Failed to read Angel prompt file: %s", e, exc_info=True
                    )
                    logger.warning(
                        "Using fallback Angel prompt (hardcoded default)", exc_info=True
                    )
                    self._angel_prompt = FALLBACK_ANGEL_PROMPT
            else:
                logger.warning("Angel prompt file not found: %s", angel_prompt_path)
                logger.warning("Using fallback Angel prompt (hardcoded default)")
                self._angel_prompt = FALLBACK_ANGEL_PROMPT

            # Load steering template with fallback
            steering_template_path = self.prompts_dir / "steering_template.md"
            if steering_template_path.exists():
                try:
                    with open(steering_template_path, encoding="utf-8") as f:
                        self._steering_template = f.read().strip()

                    if not self._steering_template:
                        logger.warning("Steering template file is empty")
                        logger.warning(
                            "Using fallback steering template (hardcoded default)"
                        )
                        self._steering_template = FALLBACK_STEERING_TEMPLATE
                except Exception as e:
                    logger.warning(
                        "Failed to read steering template file: %s", e, exc_info=True
                    )
                    logger.warning(
                        "Using fallback steering template (hardcoded default)",
                        exc_info=True,
                    )
                    self._steering_template = FALLBACK_STEERING_TEMPLATE
            else:
                logger.warning(
                    "Steering template file not found: %s", steering_template_path
                )
                logger.warning("Using fallback steering template (hardcoded default)")
                self._steering_template = FALLBACK_STEERING_TEMPLATE

            self._loaded = True

            logger.info(
                "Successfully loaded Angel prompts: angel_prompt=%d chars, steering_template=%d chars",
                len(self._angel_prompt),
                len(self._steering_template),
            )

        except Exception as e:
            logger.error(f"Failed to load Angel prompts: {e}", exc_info=True)
            raise

    @property
    def angel_prompt(self) -> str:
        """
        Get the Angel instruction prompt.

        Returns:
            Angel prompt text

        Raises:
            RuntimeError: If prompts haven't been loaded yet
        """
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._angel_prompt is None:
            raise RuntimeError("Angel prompt not available.")
        return self._angel_prompt

    @property
    def steering_template(self) -> str:
        """
        Get the steering message template.

        Returns:
            Steering message template

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

    def get_prompt_info(self) -> AngelPromptInfo:
        """
        Get information about loaded prompts.

        Returns:
            AngelPromptInfo with loading status and metadata
        """
        if not self._loaded:
            return AngelPromptInfo(loaded=False)

        return AngelPromptInfo(
            loaded=True,
            prompts_dir=str(self.prompts_dir),
            angel_prompt_length=len(self._angel_prompt or ""),
            steering_template_length=len(self._steering_template or ""),
        )
