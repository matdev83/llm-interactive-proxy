"""
DEPRECATED: Legacy proxy logic module.

This module is kept for backward compatibility and will be removed in a future version.
Please use the new SOLID architecture in `src/core/` instead.
"""

import warnings
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

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
    """
    
    def __init__(
        self,
        **kwargs
    ):
        """Initialize proxy state with default values."""
        warnings.warn(
            "ProxyState is deprecated. Use SessionState from src/core/domain/session.py instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        # Backend and model settings
        self.override_backend = kwargs.get("override_backend", None)
        self.override_model = kwargs.get("override_model", None)
        self.openai_url = kwargs.get("openai_url", None)
        
        # Project settings
        self.project = kwargs.get("project", None)
        self.project_dir = kwargs.get("project_dir", None)
        
        # Reasoning settings
        self.reasoning_effort = kwargs.get("reasoning_effort", 0)
        self.thinking_budget = kwargs.get("thinking_budget", 0)
        self.temperature = kwargs.get("temperature", 0.7)
        
        # Loop detection settings
        self.loop_detection_enabled = kwargs.get("loop_detection_enabled", True)
        self.loop_detection_buffer_size = kwargs.get("loop_detection_buffer_size", 2048)
        self.tool_loop_detection_enabled = kwargs.get("tool_loop_detection_enabled", True)
        self.tool_loop_max_repeats = kwargs.get("tool_loop_max_repeats", 4)
        self.tool_loop_ttl_seconds = kwargs.get("tool_loop_ttl_seconds", 120)
        self.tool_loop_mode = kwargs.get("tool_loop_mode", "break")
        
        # Additional settings
        self.failover_routes = kwargs.get("failover_routes", {})
        self.interactive_mode = kwargs.get("interactive_mode", True)


# Keep other utility functions that might be used by legacy code
def extract_client_info(headers: Dict[str, str], client_id_header: str = "X-Client-ID") -> Dict[str, Any]:
    """
    DEPRECATED: Extract client information from headers.
    
    This function is kept for backward compatibility and will be removed in a future version.
    """
    warnings.warn(
        "extract_client_info is deprecated. Use the new architecture instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    client_info = {}
    client_info["client_id"] = headers.get(client_id_header, "unknown")
    client_info["user_agent"] = headers.get("user-agent", "unknown")
    return client_info


def extract_raw_prompt(messages: List[Dict[str, Any]]) -> str:
    """
    DEPRECATED: Extract raw prompt from messages.
    
    This function is kept for backward compatibility and will be removed in a future version.
    Please use RequestProcessor._extract_raw_prompt in src/core/services/request_processor.py instead.
    """
    warnings.warn(
        "extract_raw_prompt is deprecated. Use RequestProcessor._extract_raw_prompt instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    if not messages:
        return ""
    
    # Find the last user message
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if content and isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Handle multipart content
                texts = []
                for part in content:
                    if part.get("type") == "text":
                        texts.append(part.get("text", ""))
                return " ".join(texts)
    
    return ""
