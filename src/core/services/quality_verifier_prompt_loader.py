"""Quality Verifier prompt loader service."""

from pathlib import Path

from pydantic import BaseModel

from src.core.common.logging_utils import get_logger

logger = get_logger(__name__)


class QualityVerifierPromptInfo(BaseModel):
    """Metadata about loaded Quality Verifier prompts."""

    loaded: bool
    prompts_dir: str | None = None
    quality_verifier_prompt_length: int = 0
    steering_template_length: int = 0
    quality_verifier_tail_reminder_length: int = 0

    model_config = {"extra": "forbid"}


FALLBACK_QUALITY_VERIFIER_PROMPT = (
    "You are `Quality Verifier`, a private assessment and steering helper for the Main Assistant.\n"
    "Your feedback is delivered privately to the Main Assistant and is NOT shown to the user.\n"
    "Do NOT mention proxy mechanics (no 'blocked', 'intercepted', 'prevented from reaching the client', etc.).\n\n"
    "Steer only when it will materially improve the next 1-3 steps in an agentic coding workflow.\n"
    "High-signal reasons to steer: the assistant is stuck/guessing, violates safety constraints, claims verification without evidence, breaks contracts, or misses an obvious next action (inspect repo, run tests, validate assumptions).\n\n"
    "You have exactly one assistant reply in this call. You MUST NOT use or request tools, function calls, or any multi-step actions—only plain text in the required format.\n\n"
    "Output protocol (strict): return EXACTLY ONE of the following XML forms. No extra text before or after. No Markdown fences.\n"
    "- <status>NO_STEERING_NEEDED</status>\n"
    "- <steering>...1-8 sentences, specific next actions + how to verify...</steering>\n"
)

FALLBACK_STEERING_TEMPLATE = (
    "You are receiving a private steering note from `Quality Verifier`.\n\n"
    "This note is not from the user. Do not quote it to the user or mention any verification system.\n"
    "Use it only to adjust your plan and improve progress on the user's request.\n\n"
    "<quality_verifier_steering>\n{quality_verifier_steering_message}\n</quality_verifier_steering>\n"
)

# Inner text only; QualityVerifierService wraps it in <system-reminder>...</system-reminder>.
FALLBACK_QUALITY_VERIFIER_TAIL_REMINDER = (
    "Remember before you answer:\n"
    "- You judge only the last assistant message (the Main Assistant's latest reply).\n"
    "- Output exactly one of: <status>NO_STEERING_NEEDED</status> or <steering>...</steering> "
    "— no other text, no markdown fences, no tool calls.\n"
    "- Steer only for high-signal issues that improve the next 1-3 steps; skip nitpicks.\n"
    "- Never mention proxy or verification mechanics (private feedback to the Main Assistant)."
)


class QualityVerifierPromptLoader:
    """Load and cache Quality Verifier prompts from files."""

    def __init__(self, prompts_dir: str | None = None):
        self.prompts_dir = (
            Path("config/prompts/quality_verifier_prompts")
            if prompts_dir is None
            else Path(prompts_dir)
        )
        self._quality_verifier_prompt: str | None = None
        self._steering_template: str | None = None
        self._quality_verifier_tail_reminder: str | None = None
        self._loaded = False

    def load_prompts(self) -> None:
        """Load all prompts with fallbacks for missing files."""
        try:
            logger.info("Loading Quality Verifier prompts from %s", self.prompts_dir)

            prompt_path = self.prompts_dir / "quality_verifier_prompt.md"
            if prompt_path.exists():
                try:
                    self._quality_verifier_prompt = prompt_path.read_text(
                        encoding="utf-8"
                    ).strip()
                except Exception as e:
                    logger.warning(
                        "Failed to read Quality Verifier prompt file: %s",
                        e,
                        exc_info=True,
                    )

            if not self._quality_verifier_prompt:
                logger.warning(
                    "Using fallback Quality Verifier prompt (hardcoded default)"
                )
                self._quality_verifier_prompt = FALLBACK_QUALITY_VERIFIER_PROMPT

            steering_path = self.prompts_dir / "steering_template.md"
            if steering_path.exists():
                try:
                    self._steering_template = steering_path.read_text(
                        encoding="utf-8"
                    ).strip()
                except Exception as e:
                    logger.warning(
                        "Failed to read steering template file: %s",
                        e,
                        exc_info=True,
                    )

            if not self._steering_template:
                logger.warning("Using fallback steering template (hardcoded default)")
                self._steering_template = FALLBACK_STEERING_TEMPLATE

            tail_path = self.prompts_dir / "quality_verifier_tail_reminder.md"
            if tail_path.exists():
                try:
                    self._quality_verifier_tail_reminder = tail_path.read_text(
                        encoding="utf-8"
                    ).strip()
                except Exception as e:
                    logger.warning(
                        "Failed to read Quality Verifier tail reminder file: %s",
                        e,
                        exc_info=True,
                    )
                    self._quality_verifier_tail_reminder = None

            if self._quality_verifier_tail_reminder is None:
                self._quality_verifier_tail_reminder = (
                    FALLBACK_QUALITY_VERIFIER_TAIL_REMINDER
                )

            self._loaded = True
            logger.info(
                "Successfully loaded Quality Verifier prompts: quality_verifier_prompt=%d chars, "
                "steering_template=%d chars, tail_reminder=%d chars",
                len(self._quality_verifier_prompt),
                len(self._steering_template),
                len(self._quality_verifier_tail_reminder),
            )
        except Exception as e:
            logger.error(
                "Failed to load Quality Verifier prompts: %s", e, exc_info=True
            )
            raise

    @property
    def quality_verifier_prompt(self) -> str:
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._quality_verifier_prompt is None:
            raise RuntimeError("Quality Verifier prompt not available.")
        return self._quality_verifier_prompt

    @property
    def steering_template(self) -> str:
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._steering_template is None:
            raise RuntimeError("Steering template not available.")
        return self._steering_template

    @property
    def quality_verifier_tail_reminder(self) -> str:
        """Inner reminder text (no XML wrapper).

        Loaded from ``quality_verifier_tail_reminder.md``. An empty file disables the
        tail reminder. When the file is missing, a built-in fallback is used.
        """
        if not self._loaded:
            raise RuntimeError("Prompts not loaded. Call load_prompts() first.")
        if self._quality_verifier_tail_reminder is None:
            raise RuntimeError("Quality Verifier tail reminder not available.")
        return self._quality_verifier_tail_reminder

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def reload_prompts(self) -> None:
        self._loaded = False
        self._quality_verifier_tail_reminder = None
        self.load_prompts()

    def get_prompt_info(self) -> QualityVerifierPromptInfo:
        if not self._loaded:
            return QualityVerifierPromptInfo(loaded=False)

        return QualityVerifierPromptInfo(
            loaded=True,
            prompts_dir=str(self.prompts_dir),
            quality_verifier_prompt_length=len(self._quality_verifier_prompt or ""),
            steering_template_length=len(self._steering_template or ""),
            quality_verifier_tail_reminder_length=len(
                self._quality_verifier_tail_reminder or ""
            ),
        )
