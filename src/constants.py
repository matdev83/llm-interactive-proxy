from enum import Enum

DEFAULT_COMMAND_PREFIX: str = "!/"


class AgentType(str, Enum):
    """Enum for supported agent types."""

    CLINE = "cline"
    ROOCODE = "roocode"
    AIDER = "aider"


class ConfigKey(str, Enum):
    """Enum for configuration keys."""

    BACKEND = "backend"
    DEFAULT_BACKEND = "default_backend"
    DISABLE_AUTH = "disable_auth"
    DISABLE_ACCOUNTING = "disable_accounting"
    DISABLE_INTERACTIVE_COMMANDS = "disable_interactive_commands"
    INTERACTIVE_MODE = "interactive_mode"
    COMMAND_PREFIX = "command_prefix"
    PROXY_TIMEOUT = "proxy_timeout"
    OPENROUTER_API_KEYS = "openrouter_api_keys"
    GEMINI_API_KEYS = "gemini_api_keys"
    OPENROUTER_API_BASE_URL = "openrouter_api_base_url"
    GEMINI_API_BASE_URL = "gemini_api_base_url"
    GOOGLE_CLOUD_PROJECT = "google_cloud_project"
