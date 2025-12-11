"""
Gemini Base Connector Package.

This package provides the base classes and utilities for Gemini OAuth connectors.
The main connector class is broken down into focused, composable modules:

- token_manager: OAuth token lifecycle management
- credential_loader: Credential loading, saving, and validation
- credentials: Pluggable credential providers (file, SQLite)
- file_watcher: File system monitoring for credential changes
- graceful_degradation: Rate limit handling
- stream_processor: Streaming response utilities
- prompt_limiter: Prompt size enforcement
- tool_sanitizer: Tool format conversion
- project_discovery: Project ID discovery strategies
- model_discovery: Model enumeration strategies
- endpoints: API endpoint configurations
- request_builders: Request body formatting strategies
- response_processors: Response post-processing strategies
- interfaces: Protocol definitions for all strategies
- generation_config_builder: Generation config building utilities
- model_validation: Model name validation and mapping
- response_accumulator: Streaming response accumulation
- response_text_extractor: Response text extraction
- retry_delay_parser: Retry delay parsing utilities
- thought_signature_manager: Thought signature caching
- user_prompt_id_generator: User prompt ID generation
"""

from .chat_request_preparer import (
    ChatRequestPreparer,
    PreparedChatRequest,
)
from .connector import GeminiOAuthBaseConnector
from .credential_loader import CredentialLoader
from .credential_providers import (
    AntigravitySQLiteCredentialProvider,
    FileCredentialProvider,
)
from .endpoints import (
    ANTIGRAVITY_SANDBOX_ENDPOINT,
    ANTIGRAVITY_USER_AGENT,
    CODE_ASSIST_ENDPOINT,
    AntigravitySandboxEndpoint,
    StandardCodeAssistEndpoint,
)
from .file_watcher import FileWatcher, FileWatcherState

# New extracted modules
from .generation_config_builder import (
    GenerationConfigBuilder,
    build_code_assist_request_format,
    convert_from_code_assist_format,
)
from .graceful_degradation import (
    GracefulDegradationManager,
    calculate_retry_delay,
    is_model_in_cooldown,
    is_rate_limit_like_error,
    set_model_cooldown,
)
from .interfaces import (
    ICredentialProvider,
    IEndpointConfig,
    IHealthCheckStrategy,
    IModelDiscoveryStrategy,
    IProjectDiscoveryStrategy,
    IRequestBodyBuilder,
    IResponsePostProcessor,
)
from .model_discovery import ApiModelDiscovery, FallbackModelDiscovery
from .model_validation import (
    GOOGLE_VENDOR_PREFIX,
    ModelListManager,
    ModelValidator,
)
from .project_discovery import (
    AntigravityProjectDiscovery,
    FreeTierProjectDiscovery,
    PaidTierProjectDiscovery,
    build_client_metadata,
    calculate_tier_score,
    extract_project_id_from_response,
    select_best_tier,
)
from .prompt_limiter import enforce_prompt_limit, estimate_prompt_tokens
from .request_builders import AntigravityRequestBodyBuilder, StandardRequestBodyBuilder
from .response_accumulator import (
    StreamingResponseAccumulator,
    response_envelope_to_stream_chunk,
)
from .response_processors import NoOpResponsePostProcessor, XmlToolCallPostProcessor
from .response_text_extractor import (
    ResponseTextExtractor,
    extract_generated_text_from_response,
)
from .retry_delay_parser import (
    extract_retry_delay,
    parse_duration_string,
    parse_retry_from_message,
)
from .stream_processor import (
    build_error_chunk,
    coerce_chunk_to_dict,
    extract_usage_from_response,
    normalize_chunk,
    process_chunk_for_streaming,
    should_skip_chunk,
)
from .thought_signature_manager import (
    ThoughtSignatureManager,
    get_global_thought_signature_manager,
)
from .token_manager import TokenManager
from .tool_sanitizer import sanitize_code_assist_tools
from .user_prompt_id_generator import generate_user_prompt_id

__all__ = [
    # Main connector
    "GeminiOAuthBaseConnector",
    # Strategy interfaces (protocols)
    "ICredentialProvider",
    "IEndpointConfig",
    "IHealthCheckStrategy",
    "IModelDiscoveryStrategy",
    "IProjectDiscoveryStrategy",
    "IRequestBodyBuilder",
    "IResponsePostProcessor",
    # Credential providers
    "AntigravitySQLiteCredentialProvider",
    "CredentialLoader",
    "FileCredentialProvider",
    # Endpoint configurations
    "ANTIGRAVITY_SANDBOX_ENDPOINT",
    "ANTIGRAVITY_USER_AGENT",
    "AntigravitySandboxEndpoint",
    "CODE_ASSIST_ENDPOINT",
    "StandardCodeAssistEndpoint",
    # Request builders
    "AntigravityRequestBodyBuilder",
    "StandardRequestBodyBuilder",
    # Project discovery
    "AntigravityProjectDiscovery",
    "FreeTierProjectDiscovery",
    "PaidTierProjectDiscovery",
    # Model discovery
    "ApiModelDiscovery",
    "FallbackModelDiscovery",
    # Response processors
    "NoOpResponsePostProcessor",
    "XmlToolCallPostProcessor",
    # Token and file management
    "FileWatcher",
    "FileWatcherState",
    "GracefulDegradationManager",
    "calculate_retry_delay",
    "is_model_in_cooldown",
    "is_rate_limit_like_error",
    "set_model_cooldown",
    "TokenManager",
    # Backward-compatible helpers
    "build_client_metadata",
    "build_error_chunk",
    "calculate_tier_score",
    "coerce_chunk_to_dict",
    "enforce_prompt_limit",
    "estimate_prompt_tokens",
    "extract_project_id_from_response",
    "extract_usage_from_response",
    "normalize_chunk",
    "process_chunk_for_streaming",
    "sanitize_code_assist_tools",
    "select_best_tier",
    "should_skip_chunk",
    # Chat request preparation
    "ChatRequestPreparer",
    "PreparedChatRequest",
    # New extracted modules
    "GenerationConfigBuilder",
    "GOOGLE_VENDOR_PREFIX",
    "ModelListManager",
    "ModelValidator",
    "ResponseTextExtractor",
    "StreamingResponseAccumulator",
    "ThoughtSignatureManager",
    "build_code_assist_request_format",
    "convert_from_code_assist_format",
    "extract_generated_text_from_response",
    "extract_retry_delay",
    "generate_user_prompt_id",
    "get_global_thought_signature_manager",
    "parse_duration_string",
    "parse_retry_from_message",
    "response_envelope_to_stream_chunk",
]
