# Adding Backends

This guide covers how to add new backend connectors to the LLM Interactive Proxy, enabling support for additional LLM providers.

## Overview

Backend connectors implement the interface between the proxy's internal format and a specific LLM provider's API. Each connector handles:

- Authentication (API keys, OAuth, service accounts)
- Request translation (internal format to provider-specific format)
- Response translation (provider-specific format to internal format)
- Streaming support with proper cancellation
- Model discovery and listing
- Error handling and retry logic

## Architecture

All backend connectors inherit from the `LLMBackend` abstract base class defined in `src/connectors/base.py`. This ensures a consistent interface across all providers.

### Base Class Structure

```python
class LLMBackend(abc.ABC):
    backend_type: str  # Unique identifier for this backend
    
    def __init__(self, config: AppConfig, response_processor: IResponseProcessor | None = None):
        self._response_processor = response_processor
        self.config = config
    
    @abc.abstractmethod
    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Forward a chat completion request to the LLM backend."""
    
    @abc.abstractmethod
    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the backend with configuration."""
    
    def get_available_models(self) -> list[str]:
        """Get a list of available models for this backend."""
        return []
```

## Creating a New Backend

### Step 1: Create the Connector File

Create a new file in `src/connectors/` named after your provider (e.g., `my_provider.py`).

### Step 2: Implement the Base Class

```python
from __future__ import annotations

import logging
from typing import Any

import httpx

from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class MyProviderBackend(LLMBackend):
    """Backend connector for MyProvider API."""
    
    backend_type: str = "my-provider"
    
    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        super().__init__(config)
        self.client = client
        self.translation_service = translation_service
        self.available_models: list[str] = []
        self.api_key: str | None = None
        self.api_base_url: str = "https://api.myprovider.com/v1"
    
    async def initialize(self, **kwargs: Any) -> None:
        """Initialize with API credentials and fetch available models."""
        self.api_key = kwargs.get("api_key")
        if "api_base_url" in kwargs:
            self.api_base_url = kwargs["api_base_url"]
        
        # Fetch available models (optional but recommended)
        if self.api_key:
            try:
                await self._fetch_models()
            except Exception as e:
                logger.warning(f"Failed to fetch models: {e}")
    
    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completion requests."""
        # Convert domain request to provider format
        payload = self._prepare_payload(request_data, processed_messages, effective_model)
        
        # Prepare headers
        headers = self._get_headers(identity)
        
        # Handle streaming vs non-streaming
        if request_data.stream:
            return await self._handle_streaming(payload, headers)
        else:
            return await self._handle_non_streaming(payload, headers)
```

### Step 3: Implement Request Translation

Convert the proxy's internal domain format to your provider's API format:

```python
def _prepare_payload(
    self,
    request_data: ChatRequest,
    processed_messages: list[Any],
    effective_model: str,
) -> dict[str, Any]:
    """Convert domain request to provider-specific format."""
    # Use TranslationService to convert from domain format
    payload = self.translation_service.from_domain_request(request_data, "openai")
    
    # Apply provider-specific transformations
    payload["model"] = effective_model
    payload["stream"] = bool(request_data.stream)
    
    # Handle provider-specific parameters
    if request_data.temperature is not None:
        payload["temperature"] = request_data.temperature
    
    # Use processed_messages (already filtered and transformed)
    if processed_messages:
        payload["messages"] = self._normalize_messages(processed_messages)
    
    return payload
```

### Step 4: Implement Response Translation

Convert provider responses back to the proxy's internal format:

```python
async def _handle_non_streaming(
    self,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> ResponseEnvelope:
    """Handle non-streaming responses."""
    url = f"{self.api_base_url}/chat/completions"
    
    try:
        response = await self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.RequestError as e:
        raise ServiceUnavailableError(f"Could not connect to provider: {e}")
    
    # Convert provider response to domain format
    data = response.json()
    domain_response = self.translation_service.to_domain_response(data, "openai")
    
    return ResponseEnvelope(
        content=domain_response.model_dump(),
        status_code=response.status_code,
        headers=dict(response.headers),
        usage=domain_response.usage,
    )
```

### Step 5: Implement Streaming Support

For streaming responses, implement proper chunk handling and cancellation:

```python
async def _handle_streaming(
    self,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> StreamingResponseEnvelope:
    """Handle streaming responses with cancellation support."""
    url = f"{self.api_base_url}/chat/completions"
    
    request = self.client.build_request("POST", url, json=payload, headers=headers)
    response = await self.client.send(request, stream=True)
    
    if response.status_code >= 400:
        await response.aclose()
        raise BackendError(f"Provider returned {response.status_code}")
    
    async def event_stream():
        try:
            async for chunk in response.aiter_text():
                # Convert provider chunk to domain format
                domain_chunk = self.translation_service.to_domain_stream_chunk(
                    chunk, "openai"
                )
                yield ProcessedResponse(content=domain_chunk)
        finally:
            await response.aclose()
    
    async def cancel_stream():
        """Cancel the streaming request."""
        await response.aclose()
    
    return StreamingResponseHandle(
        iterator=event_stream(),
        cancel_callback=cancel_stream,
        headers=dict(response.headers),
    )
```

### Step 6: Register the Backend

Register your backend in `src/core/services/backend_registry.py`:

```python
from src.connectors.my_provider import MyProviderBackend

# In the registration function
backend_registry.register("my-provider", MyProviderBackend)
```

## Translation Service Integration

The proxy uses `TranslationService` to convert between different formats. Your backend should leverage this service for consistency.

### Supported Conversions

- `from_domain_request(request, target_format)` - Convert domain ChatRequest to provider format
- `to_domain_response(response, source_format)` - Convert provider response to domain format
- `to_domain_stream_chunk(chunk, source_format)` - Convert streaming chunk to domain format

### Example Usage

```python
# Convert domain request to OpenAI-compatible format
payload = self.translation_service.from_domain_request(request_data, "openai")

# Convert provider response to domain format
domain_response = self.translation_service.to_domain_response(data, "openai")

# Convert streaming chunk to domain format
domain_chunk = self.translation_service.to_domain_stream_chunk(chunk, "openai")
```

## Authentication Patterns

### API Key Authentication

```python
def _get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
    """Build request headers with authentication."""
    headers = {
        "Authorization": f"Bearer {self.api_key}",
        "Content-Type": "application/json",
    }
    
    # Add identity headers if provided
    if identity:
        headers.update(identity.get_resolved_headers(None))
    
    # Add loop prevention header
    from src.core.security.loop_prevention import ensure_loop_guard_header
    return ensure_loop_guard_header(headers)
```

### OAuth Authentication

For OAuth-based backends (like Gemini OAuth):

```python
async def initialize(self, **kwargs: Any) -> None:
    """Initialize with OAuth credentials."""
    self.oauth_creds_path = kwargs.get("oauth_creds_path", "oauth_creds.json")
    await self._load_oauth_credentials()
    await self._refresh_token_if_needed()

async def _load_oauth_credentials(self) -> None:
    """Load OAuth credentials from file."""
    with open(self.oauth_creds_path) as f:
        self.oauth_creds = json.load(f)

async def _refresh_token_if_needed(self) -> None:
    """Refresh OAuth token if expired or expiring soon."""
    if self._is_token_expired():
        await self._refresh_token()
```

## Error Handling

Use the proxy's exception hierarchy for consistent error handling:

```python
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)

# Authentication failures
if not self.api_key:
    raise AuthenticationError(
        message="API key not configured",
        code="missing_api_key"
    )

# Network failures
try:
    response = await self.client.post(url, json=payload)
except httpx.RequestError as e:
    raise ServiceUnavailableError(
        message=f"Could not connect to provider: {e}"
    )

# Provider errors
if response.status_code >= 400:
    raise BackendError(
        message=f"Provider returned error: {response.text}",
        code="provider_error",
        status_code=response.status_code,
    )
```

## Testing Your Backend

### Unit Tests

Create unit tests in `tests/unit/connectors/test_my_provider.py`:

```python
import pytest
from unittest.mock import AsyncMock, Mock

from src.connectors.my_provider import MyProviderBackend


@pytest.mark.asyncio
async def test_chat_completions_non_streaming():
    """Test non-streaming chat completions."""
    # Setup
    mock_client = AsyncMock()
    mock_config = Mock()
    mock_translation = Mock()
    
    backend = MyProviderBackend(mock_client, mock_config, mock_translation)
    await backend.initialize(api_key="test-key")
    
    # Mock response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [...]}
    mock_client.post.return_value = mock_response
    
    # Execute
    request_data = Mock(stream=False, temperature=0.7)
    result = await backend.chat_completions(
        request_data, [], "test-model"
    )
    
    # Verify
    assert result.status_code == 200
    mock_client.post.assert_called_once()
```

### Integration Tests

Test against the actual provider API (with appropriate credentials):

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_api_call():
    """Test actual API call to provider."""
    import os
    api_key = os.getenv("MY_PROVIDER_API_KEY")
    if not api_key:
        pytest.skip("API key not configured")
    
    # Test with real API
    ...
```

## Configuration

Add configuration support in `src/core/config/app_config.py`:

```python
class AppConfig:
    # ... existing fields ...
    
    my_provider_api_key: str | None = None
    my_provider_api_base_url: str | None = None
```

Add CLI arguments in `src/core/cli.py`:

```python
parser.add_argument(
    "--my-provider-api-key",
    help="API key for MyProvider",
    default=os.getenv("MY_PROVIDER_API_KEY"),
)
```

## Best Practices

1. **Use TranslationService**: Leverage the translation service for format conversions
2. **Handle Errors Gracefully**: Use the proxy's exception hierarchy
3. **Support Streaming**: Implement proper streaming with cancellation
4. **Add Loop Prevention**: Use `ensure_loop_guard_header()` on all requests
5. **Log Appropriately**: Use structured logging for debugging
6. **Test Thoroughly**: Write both unit and integration tests
7. **Document Configuration**: Add clear documentation for setup
8. **Handle Rate Limits**: Implement retry logic with exponential backoff
9. **Validate Inputs**: Check for required parameters before making requests
10. **Clean Up Resources**: Properly close connections and streams

## Example Backends

Study these existing backends for reference:

- **OpenAI** (`src/connectors/openai.py`) - Standard REST API with streaming
- **Anthropic** (`src/connectors/anthropic.py`) - SSE streaming with message cancellation
- **Gemini OAuth** (`src/connectors/gemini_oauth_base.py`) - OAuth authentication pattern
- **Hybrid** (`src/connectors/hybrid.py`) - Virtual backend orchestrating multiple models

## Related Documentation

- [Architecture](architecture.md) - System architecture overview
- [Code Organization](code-organization.md) - Codebase structure
- [Testing](testing.md) - Testing guidelines
- [AGENTS.md](../../dev/AGENTS.md) - Coding standards
