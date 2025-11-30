"""
Gemini Base Connector Package.

This package provides the base classes and utilities for Gemini OAuth connectors.
The main connector class is broken down into focused, composable modules:

- token_manager: OAuth token lifecycle management
- credential_loader: Credential loading, saving, and validation
- file_watcher: File system monitoring for credential changes
- graceful_degradation: Rate limit handling and model fallback
- stream_processor: Streaming response utilities
- prompt_limiter: Prompt size enforcement
- tool_sanitizer: Tool format conversion
- project_discovery: Project ID discovery helpers
"""

from .connector import GeminiOAuthBaseConnector
from .credential_loader import CredentialLoader
from .file_watcher import FileWatcher, FileWatcherState
from .graceful_degradation import GracefulDegradationManager
from .project_discovery import (
    build_client_metadata,
    calculate_tier_score,
    extract_project_id_from_response,
    select_best_tier,
)
from .prompt_limiter import enforce_prompt_limit, estimate_prompt_tokens
from .stream_processor import (
    build_error_chunk,
    extract_usage_from_response,
    should_skip_chunk,
)
from .token_manager import TokenManager
from .tool_sanitizer import sanitize_code_assist_tools

__all__ = [
    "GeminiOAuthBaseConnector",
    "CredentialLoader",
    "FileWatcher",
    "FileWatcherState",
    "GracefulDegradationManager",
    "TokenManager",
    "build_client_metadata",
    "build_error_chunk",
    "calculate_tier_score",
    "enforce_prompt_limit",
    "estimate_prompt_tokens",
    "extract_project_id_from_response",
    "extract_usage_from_response",
    "sanitize_code_assist_tools",
    "select_best_tier",
    "should_skip_chunk",
]
