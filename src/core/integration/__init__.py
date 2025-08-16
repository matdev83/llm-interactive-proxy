# Integration package

from src.core.integration.bridge import (
    IntegrationBridge,
    get_integration_bridge,
    set_integration_bridge,
)
from src.core.integration.hybrid_controller import (
    hybrid_anthropic_messages,
    hybrid_chat_completions,
)

__all__ = [
    "IntegrationBridge",
    "get_integration_bridge",
    "hybrid_anthropic_messages",
    "hybrid_chat_completions",
    "set_integration_bridge",
]