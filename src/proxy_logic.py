import logging
import warnings
from typing import Any  # Add Dict import

from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode
from src.tool_call_loop.tracker import ToolCallTracker

logger = logging.getLogger(__name__)

# Show deprecation warning when this module is imported
warnings.warn(
    "The proxy_logic module is deprecated and will be removed in a future version. "
    "Please use the new SOLID architecture in src/core/ instead.",
    DeprecationWarning,
    stacklevel=2
)


class ProxyState:
    """
    DEPRECATED: Legacy proxy state class.
    
    This class is kept for backward compatibility and will be removed in a future version.
    Please use the new SessionState in src/core/domain/session.py instead.
    
    Manages the state of the proxy, particularly model overrides.
    """

    def __init__(
        self,
        interactive_mode: bool = True,
        failover_routes: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.override_backend: str | None = None
        self.override_model: str | None = None
        self.oneoff_backend: str | None = None
        self.oneoff_model: str | None = None
        self.invalid_override: bool = False
        self.project: str | None = None
        self.project_dir: str | None = None
        self.interactive_mode: bool = interactive_mode
        self.interactive_just_enabled: bool = False
        self.hello_requested: bool = False
        self.is_cline_agent: bool = False
        self.failover_routes: dict[str, dict[str, Any]] = (
            failover_routes if failover_routes is not None else {}
        )
        # Reasoning configuration
        self.reasoning_effort: str | None = None
        self.reasoning_config: dict[str, Any] | None = None

        # Gemini-specific reasoning configuration
        self.thinking_budget: int | None = None
        self.gemini_generation_config: dict[str, Any] | None = None

        # Temperature configuration
        self.temperature: float | None = None

        # OpenAI URL configuration
        self.openai_url: str | None = None

        # Loop detection session-level override (None = use defaults)
        self.loop_detection_enabled: bool | None = None

        # Tool call loop detection session-level overrides (None = use defaults)
        self.tool_loop_detection_enabled: bool | None = None
        self.tool_loop_max_repeats: int | None = None
        self.tool_loop_ttl_seconds: int | None = None
        self.tool_loop_mode: ToolLoopMode | None = None

        # Per-session tool call tracker (for thread safety)
        self.tool_call_tracker: ToolCallTracker | None = None

    def set_override_model(
        self, backend: str, model_name: str, *, invalid: bool = False
    ) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "ProxyState.set_override_model called with: backend=%s, model_name=%s, invalid=%s",
                backend,
                model_name,
                invalid,
            )
        self.override_backend = backend
        self.override_model = model_name
        self.invalid_override = invalid

    def set_oneoff_route(self, backend: str, model_name: str) -> None:
        """Sets a one-off route for the very next request."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting one-off route to: %s:%s", backend, model_name)
        self.oneoff_backend = backend
        self.oneoff_model = model_name

    def clear_oneoff_route(self) -> None:
        """Clears the one-off route."""
        if self.oneoff_backend or self.oneoff_model:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Clearing one-off route.")
            self.oneoff_backend = None
            self.oneoff_model = None

    def set_override_backend(self, backend: str) -> None:
        """Override only the backend to use for this session."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Setting override backend to: %s for ProxyState ID: %s",
                backend,
                id(self),
            )
        self.override_backend = backend
        self.override_model = None
        self.invalid_override = False

    def unset_override_model(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting override model.")
        self.override_backend = None
        self.override_model = None
        self.invalid_override = False

    def unset_override_backend(self) -> None:
        """Remove any backend override."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting override backend.")
        self.override_backend = None
        self.override_model = None
        self.invalid_override = False

    def set_project(self, project_name: str) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting project to: %s", project_name)
        self.project = project_name

    def unset_project(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting project.")
        self.project = None

    def set_project_dir(self, project_dir: str) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting project directory to: %s", project_dir)
        self.project_dir = project_dir

    def unset_project_dir(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting project directory.")
        self.project_dir = None

    def set_interactive_mode(self, value: bool) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting interactive mode to: %s", value)
        if value and not self.interactive_mode:
            self.interactive_just_enabled = True
        else:
            self.interactive_just_enabled = False
        self.interactive_mode = value

    def unset_interactive_mode(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting interactive mode (setting to False).")
        self.interactive_mode = False
        self.interactive_just_enabled = False

    # Failover route management ----------------------------------------------
    def create_failover_route(self, name: str, policy: str) -> None:
        self.failover_routes[name] = {"policy": policy, "elements": []}

    def delete_failover_route(self, name: str) -> None:
        self.failover_routes.pop(name, None)

    def clear_route(self, name: str) -> None:
        route = self.failover_routes.get(name)
        if route is not None:
            route["elements"] = []

    def append_route_element(self, name: str, element: str) -> None:
        route = self.failover_routes.setdefault(name, {"policy": "k", "elements": []})
        route.setdefault("elements", []).append(element)

    def prepend_route_element(self, name: str, element: str) -> None:
        route = self.failover_routes.setdefault(name, {"policy": "k", "elements": []})
        route.setdefault("elements", []).insert(0, element)

    def list_routes(self) -> dict[str, str]:
        return {n: r.get("policy", "") for n, r in self.failover_routes.items()}

    def list_route(self, name: str) -> list[str]:
        route = self.failover_routes.get(name)
        if route is None:
            return []
        return list(route.get("elements", []))

    def set_is_cline_agent(self, value: bool) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting is_cline_agent to: %s", value)
        self.is_cline_agent = value

    def set_reasoning_effort(self, effort: str) -> None:
        """Set reasoning effort level for reasoning models."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting reasoning effort to: %s", effort)
        self.reasoning_effort = effort

    def unset_reasoning_effort(self) -> None:
        """Clear reasoning effort setting."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting reasoning effort.")
        self.reasoning_effort = None

    def set_reasoning_config(self, config: dict[str, Any]) -> None:
        """Set unified reasoning configuration for OpenRouter."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting reasoning config to: %s", config)
        self.reasoning_config = config

    def unset_reasoning_config(self) -> None:
        """Clear reasoning configuration."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting reasoning config.")
        self.reasoning_config = None

    def set_thinking_budget(self, budget: int) -> None:
        """Set Gemini thinking budget (128-32768 tokens)."""
        if budget < 128 or budget > 32768:
            raise ValueError("Thinking budget must be between 128 and 32768 tokens")
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting Gemini thinking budget to: %s", budget)
        self.thinking_budget = budget

    def unset_thinking_budget(self) -> None:
        """Clear Gemini thinking budget."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting Gemini thinking budget.")
        self.thinking_budget = None

    def set_gemini_generation_config(self, config: dict[str, Any]) -> None:
        """Set Gemini generation configuration."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting Gemini generation config to: %s", config)
        self.gemini_generation_config = config

    def unset_gemini_generation_config(self) -> None:
        """Clear Gemini generation configuration."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting Gemini generation config.")
        self.gemini_generation_config = None

    def set_temperature(self, temperature: float) -> None:
        """Set the temperature for the model."""
        if temperature < 0.0 or temperature > 2.0:
            raise ValueError(
                "Temperature must be between 0.0 and 2.0 (OpenAI supports up to 2.0, Gemini up to 1.0)"
            )
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting temperature to: %s", temperature)
        self.temperature = temperature

    def unset_temperature(self) -> None:
        """Clear the temperature setting."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting temperature.")
        self.temperature = None

    def set_openai_url(self, url: str) -> None:
        """Set the base URL for OpenAI API calls."""
        if not url.startswith(("http://", "https://")):
            raise ValueError("OpenAI URL must start with http:// or https://")
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting OpenAI URL to: %s", url)
        self.openai_url = url

    def unset_openai_url(self) -> None:
        """Clear the OpenAI URL setting."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting OpenAI URL.")
        self.openai_url = None

    # Loop detection ---------------------------------------------------------
    def set_loop_detection_enabled(self, enabled: bool) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting loop detection enabled override to: %s", enabled)
        self.loop_detection_enabled = enabled

    def unset_loop_detection_enabled(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting loop detection enabled override (None)")
        self.loop_detection_enabled = None

    # Tool call loop detection -------------------------------------------------
    def set_tool_loop_detection_enabled(self, enabled: bool) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Setting tool call loop detection enabled override to: %s", enabled
            )
        self.tool_loop_detection_enabled = enabled

    def unset_tool_loop_detection_enabled(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting tool call loop detection enabled override (None)")
        self.tool_loop_detection_enabled = None

    def set_tool_loop_max_repeats(self, max_repeats: int) -> None:
        if max_repeats < 2:
            raise ValueError("Tool call loop max repeats must be at least 2")
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting tool call loop max repeats to: %s", max_repeats)
        self.tool_loop_max_repeats = max_repeats

    def unset_tool_loop_max_repeats(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting tool call loop max repeats (None)")
        self.tool_loop_max_repeats = None

    def set_tool_loop_ttl_seconds(self, ttl_seconds: int) -> None:
        if ttl_seconds < 1:
            raise ValueError("Tool call loop TTL seconds must be positive")
        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting tool call loop TTL seconds to: %s", ttl_seconds)
        self.tool_loop_ttl_seconds = ttl_seconds

    def unset_tool_loop_ttl_seconds(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting tool call loop TTL seconds (None)")
        self.tool_loop_ttl_seconds = None

    def set_tool_loop_mode(self, mode: str | ToolLoopMode) -> None:
        """Set tool call loop mode; supports string with 'chance' alias and enum input."""
        if isinstance(mode, str):
            mode_str = mode.strip().lower()
            if mode_str == "chance":
                mode_str = "chance_then_break"
            try:
                enum_mode = ToolLoopMode(mode_str)
            except ValueError:
                raise ValueError(
                    "Tool call loop mode must be one of: break, chance_then_break"
                )
        else:
            enum_mode = mode

        if logger.isEnabledFor(logging.INFO):
            logger.info("Setting tool call loop mode to: %s", enum_mode.value)
        self.tool_loop_mode = enum_mode

    def unset_tool_loop_mode(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting tool call loop mode (None)")
        self.tool_loop_mode = None

    def apply_model_defaults(
        self, model_name: str, model_defaults: dict[str, Any]
    ) -> None:
        """Apply model-specific default configurations."""
        from src.models import ModelDefaults  # Import here to avoid circular imports

        try:
            # Parse model defaults if it's a dict
            if isinstance(model_defaults, dict):
                model_config = ModelDefaults(**model_defaults)
            else:
                model_config = model_defaults

            # Apply reasoning defaults if they exist and current values are not set
            if model_config.reasoning:
                reasoning_config = model_config.reasoning

                # Apply OpenAI/OpenRouter reasoning defaults
                if reasoning_config.reasoning_effort and not self.reasoning_effort:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default reasoning effort '%s' for model %s",
                            reasoning_config.reasoning_effort,
                            model_name,
                        )
                    self.reasoning_effort = reasoning_config.reasoning_effort

                if reasoning_config.reasoning and not self.reasoning_config:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default reasoning config for model %s", model_name
                        )
                    self.reasoning_config = reasoning_config.reasoning

                # Apply Gemini reasoning defaults
                if reasoning_config.thinking_budget and not self.thinking_budget:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default thinking budget %s for model %s",
                            reasoning_config.thinking_budget,
                            model_name,
                        )
                    self.thinking_budget = reasoning_config.thinking_budget

                if (
                    reasoning_config.generation_config
                    and not self.gemini_generation_config
                ):
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default generation config for model %s",
                            model_name,
                        )
                    self.gemini_generation_config = reasoning_config.generation_config

                # Apply temperature defaults
                if reasoning_config.temperature and not self.temperature:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default temperature %s for model %s",
                            reasoning_config.temperature,
                            model_name,
                        )
                    self.temperature = reasoning_config.temperature

            # Apply loop detection default if provided and not overridden in session
            if (
                getattr(model_config, "loop_detection_enabled", None) is not None
                and self.loop_detection_enabled is None
            ):
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Applying default loop_detection_enabled=%s for model %s",
                        model_config.loop_detection_enabled,
                        model_name,
                    )
                self.loop_detection_enabled = model_config.loop_detection_enabled

            # Apply tool call loop detection defaults if provided and not overridden in session
            if (
                getattr(model_config, "tool_loop_detection_enabled", None) is not None
                and self.tool_loop_detection_enabled is None
            ):
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Applying default tool_loop_detection_enabled=%s for model %s",
                        model_config.tool_loop_detection_enabled,
                        model_name,
                    )
                self.tool_loop_detection_enabled = (
                    model_config.tool_loop_detection_enabled
                )

            if self.tool_loop_max_repeats is None:
                max_repeats_value = None
                if (
                    getattr(model_config, "tool_loop_detection_max_repeats", None)
                    is not None
                ):
                    max_repeats_value = model_config.tool_loop_detection_max_repeats
                elif getattr(model_config, "tool_loop_max_repeats", None) is not None:
                    max_repeats_value = model_config.tool_loop_max_repeats

                if max_repeats_value is not None:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default tool_loop_max_repeats=%s for model %s",
                            max_repeats_value,
                            model_name,
                        )
                    self.tool_loop_max_repeats = max_repeats_value

            if self.tool_loop_ttl_seconds is None:
                ttl_value = None
                if (
                    getattr(model_config, "tool_loop_detection_ttl_seconds", None)
                    is not None
                ):
                    ttl_value = model_config.tool_loop_detection_ttl_seconds
                elif getattr(model_config, "tool_loop_ttl_seconds", None) is not None:
                    ttl_value = model_config.tool_loop_ttl_seconds

                if ttl_value is not None:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default tool_loop_ttl_seconds=%s for model %s",
                            ttl_value,
                            model_name,
                        )
                    self.tool_loop_ttl_seconds = ttl_value

            # Mode: support spec field name and previous name; accept str or enum
            if self.tool_loop_mode is None:
                mode_value = None
                if (
                    hasattr(model_config, "tool_loop_detection_mode")
                    and model_config.tool_loop_detection_mode is not None
                ):
                    mode_value = model_config.tool_loop_detection_mode
                elif getattr(model_config, "tool_loop_mode", None) is not None:
                    mode_value = model_config.tool_loop_mode

                if mode_value is not None:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applying default tool_loop_mode=%s for model %s",
                            mode_value,
                            model_name,
                        )
                    # Use setter to normalize/validate
                    self.set_tool_loop_mode(mode_value)  # type: ignore[arg-type]

        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to apply model defaults for %s: %s", model_name, e
                )

    def reset(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Resetting ProxyState instance.")
        self.override_backend = None
        self.override_model = None
        self.invalid_override = False
        self.project = None
        self.project_dir = None
        self.interactive_mode = False
        self.interactive_just_enabled = False
        self.hello_requested = False
        self.is_cline_agent = False
        self.reasoning_effort = None
        self.reasoning_config = None
        self.thinking_budget = None
        self.gemini_generation_config = None
        self.temperature = None
        self.openai_url = None
        self.loop_detection_enabled = None
        self.tool_loop_detection_enabled = None
        self.tool_loop_max_repeats = None
        self.tool_loop_ttl_seconds = None
        self.tool_loop_mode = None
        self.tool_call_tracker = None

    def get_effective_model(self, requested_model: str) -> str:
        if self.oneoff_model:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Using one-off model '%s' instead of '%s'",
                    self.oneoff_model,
                    requested_model,
                )
            return self.oneoff_model
        if self.override_model:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Overriding requested model '%s' with '%s'",
                    requested_model,
                    self.override_model,
                )
            return self.override_model
        return requested_model

    def get_selected_backend(self, default_backend: str) -> str:
        if self.oneoff_backend:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Using one-off backend '%s'", self.oneoff_backend)
            return self.oneoff_backend
        return self.override_backend or default_backend

    def get_or_create_tool_call_tracker(
        self, server_config: ToolCallLoopConfig
    ) -> ToolCallTracker:
        """Get or create a tool call tracker for this session.

        This method ensures thread safety by storing the tracker in the ProxyState
        instance rather than in a shared dictionary.

        Args:
            server_config: The server-level tool call loop configuration

        Returns:
            A ToolCallTracker instance for this session
        """
        # Create session-level override config if any overrides are set
        session_cfg = None
        if any(
            x is not None
            for x in [
                self.tool_loop_detection_enabled,
                self.tool_loop_max_repeats,
                self.tool_loop_ttl_seconds,
                self.tool_loop_mode,
            ]
        ):
            session_cfg = ToolCallLoopConfig(
                enabled=(
                    self.tool_loop_detection_enabled
                    if self.tool_loop_detection_enabled is not None
                    else True
                ),
                max_repeats=(
                    self.tool_loop_max_repeats
                    if self.tool_loop_max_repeats is not None
                    else 4
                ),
                ttl_seconds=(
                    self.tool_loop_ttl_seconds
                    if self.tool_loop_ttl_seconds is not None
                    else 120
                ),
                mode=(
                    self.tool_loop_mode
                    if self.tool_loop_mode is not None
                    else ToolLoopMode.BREAK
                ),
            )

        # Merge server config with session overrides
        effective_cfg = server_config.merge_with(session_cfg)

        # Create tracker if missing
        if self.tool_call_tracker is None:
            self.tool_call_tracker = ToolCallTracker(effective_cfg)
        else:
            # Update tracker config if overrides changed mid-session
            self.tool_call_tracker.config = effective_cfg

        return self.tool_call_tracker


# Re-export command parsing helpers from the dedicated module for backward compatibility
# from .command_parser import (
#     _process_text_for_commands,
#     get_command_pattern,
#     parse_arguments,
#     process_commands_in_messages,
# ) # Removed to break circular import

__all__ = [
    "ProxyState",
    # "parse_arguments", # Removed to break circular import
    # "get_command_pattern", # Removed to break circular import
    # "_process_text_for_commands", # Removed to break circular import
    # "process_commands_in_messages", # Removed to break circular import
    # "CommandParser", # Removed to break circular import
]
