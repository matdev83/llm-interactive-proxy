import logging
from typing import Any, Dict, List, Optional  # Add Dict import

logger = logging.getLogger(__name__)


class ProxyState:
    """Manages the state of the proxy, particularly model overrides."""

    def __init__(
        self,
        interactive_mode: bool = True,
        failover_routes: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.override_backend: Optional[str] = None
        self.override_model: Optional[str] = None
        self.oneoff_backend: Optional[str] = None
        self.oneoff_model: Optional[str] = None
        self.invalid_override: bool = False
        self.project: Optional[str] = None
        self.project_dir: Optional[str] = None
        self.interactive_mode: bool = interactive_mode
        self.interactive_just_enabled: bool = False
        self.hello_requested: bool = False
        self.is_cline_agent: bool = False
        self.failover_routes: Dict[str, Dict[str, Any]] = (
            failover_routes if failover_routes is not None else {}
        )
        # Reasoning configuration
        self.reasoning_effort: Optional[str] = None
        self.reasoning_config: Optional[Dict[str, Any]] = None

        # Gemini-specific reasoning configuration
        self.thinking_budget: Optional[int] = None
        self.gemini_generation_config: Optional[Dict[str, Any]] = None

        # Temperature configuration
        self.temperature: Optional[float] = None

    def set_override_model(
        self, backend: str, model_name: str, *, invalid: bool = False
    ) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"ProxyState.set_override_model called with: backend={backend}, model_name={model_name}, invalid={invalid}"
            )
        self.override_backend = backend
        self.override_model = model_name
        self.invalid_override = invalid

    def set_oneoff_route(self, backend: str, model_name: str) -> None:
        """Sets a one-off route for the very next request."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting one-off route to: {backend}:{model_name}")
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
                f"Setting override backend to: {backend} for ProxyState ID: {id(self)}"
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
            logger.info(f"Setting project to: {project_name}")
        self.project = project_name

    def unset_project(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting project.")
        self.project = None

    def set_project_dir(self, project_dir: str) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting project directory to: {project_dir}")
        self.project_dir = project_dir

    def unset_project_dir(self) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting project directory.")
        self.project_dir = None

    def set_interactive_mode(self, value: bool) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting interactive mode to: {value}")
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
        route = self.failover_routes.setdefault(
            name, {"policy": "k", "elements": []})
        route.setdefault("elements", []).append(element)

    def prepend_route_element(self, name: str, element: str) -> None:
        route = self.failover_routes.setdefault(
            name, {"policy": "k", "elements": []})
        route.setdefault("elements", []).insert(0, element)

    def list_routes(self) -> dict[str, str]:
        return {n: r.get("policy", "")
                for n, r in self.failover_routes.items()}

    def list_route(self, name: str) -> list[str]:
        route = self.failover_routes.get(name)
        if route is None:
            return []
        return list(route.get("elements", []))

    def set_is_cline_agent(self, value: bool) -> None:
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting is_cline_agent to: {value}")
        self.is_cline_agent = value

    def set_reasoning_effort(self, effort: str) -> None:
        """Set reasoning effort level for reasoning models."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting reasoning effort to: {effort}")
        self.reasoning_effort = effort

    def unset_reasoning_effort(self) -> None:
        """Clear reasoning effort setting."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting reasoning effort.")
        self.reasoning_effort = None

    def set_reasoning_config(self, config: Dict[str, Any]) -> None:
        """Set unified reasoning configuration for OpenRouter."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting reasoning config to: {config}")
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
            logger.info(f"Setting Gemini thinking budget to: {budget}")
        self.thinking_budget = budget

    def unset_thinking_budget(self) -> None:
        """Clear Gemini thinking budget."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting Gemini thinking budget.")
        self.thinking_budget = None

    def set_gemini_generation_config(self, config: Dict[str, Any]) -> None:
        """Set Gemini generation configuration."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting Gemini generation config to: {config}")
        self.gemini_generation_config = config

    def unset_gemini_generation_config(self) -> None:
        """Clear Gemini generation configuration."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting Gemini generation config.")
        self.gemini_generation_config = None

    def set_temperature(self, temperature: float) -> None:
        """Set the temperature for the model."""
        if temperature < 0.0 or temperature > 2.0:
            raise ValueError("Temperature must be between 0.0 and 2.0 (OpenAI supports up to 2.0, Gemini up to 1.0)")
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Setting temperature to: {temperature}")
        self.temperature = temperature

    def unset_temperature(self) -> None:
        """Clear the temperature setting."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Unsetting temperature.")
        self.temperature = None

    def apply_model_defaults(self, model_name: str, model_defaults: Dict[str, Any]) -> None:
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
                        logger.info(f"Applying default reasoning effort '{reasoning_config.reasoning_effort}' for model {model_name}")
                    self.reasoning_effort = reasoning_config.reasoning_effort
                    
                if reasoning_config.reasoning and not self.reasoning_config:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Applying default reasoning config for model {model_name}")
                    self.reasoning_config = reasoning_config.reasoning
                    
                # Apply Gemini reasoning defaults
                if reasoning_config.thinking_budget and not self.thinking_budget:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Applying default thinking budget {reasoning_config.thinking_budget} for model {model_name}")
                    self.thinking_budget = reasoning_config.thinking_budget
                    
                if reasoning_config.generation_config and not self.gemini_generation_config:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Applying default generation config for model {model_name}")
                    self.gemini_generation_config = reasoning_config.generation_config
                    
                # Apply temperature defaults
                if reasoning_config.temperature and not self.temperature:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Applying default temperature {reasoning_config.temperature} for model {model_name}")
                    self.temperature = reasoning_config.temperature
                    
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to apply model defaults for {model_name}: {e}")

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

    def get_effective_model(self, requested_model: str) -> str:
        if self.oneoff_model:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Using one-off model '{self.oneoff_model}' instead of '{requested_model}'"
                )
            return self.oneoff_model
        if self.override_model:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Overriding requested model '{requested_model}' with '{self.override_model}'"
                )
            return self.override_model
        return requested_model

    def get_selected_backend(self, default_backend: str) -> str:
        if self.oneoff_backend:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Using one-off backend '{self.oneoff_backend}'")
            return self.oneoff_backend
        return self.override_backend or default_backend


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
