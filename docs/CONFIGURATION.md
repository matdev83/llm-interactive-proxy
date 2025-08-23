# Configuration System

The LLM Interactive Proxy uses a modern, type-safe configuration system built on immutable value objects and interfaces. This document provides a comprehensive guide to understanding and working with the configuration system.

## Overview

The configuration system is designed around the following principles:

- **Type Safety**: All configuration options have proper type hints and validation
- **Immutability**: Configuration objects cannot be modified after creation
- **Interface-Based**: Services depend on interfaces, not concrete implementations
- **Composability**: Configuration can be built up from smaller, focused components
- **Testability**: Easy to mock and test with dependency injection

## Architecture

### Configuration Interfaces

The system defines several key interfaces in `src/core/interfaces/configuration.py`:

#### `IConfig`
General configuration management interface for key-value access:

```python
from src.core.interfaces.configuration import IConfig

def my_function(config: IConfig):
    api_timeout = config.get("api_timeout", 30)
    debug_mode = config.get("debug_mode", False)
```

#### `IBackendConfig`
Backend-specific configuration for LLM providers:

```python
from src.core.interfaces.configuration import IBackendConfig

def setup_backend(config: IBackendConfig):
    backend_type = config.backend_type  # "openai", "anthropic", etc.
    model = config.model               # "gpt-4", "claude-3", etc.
    api_url = config.api_url          # Custom API endpoint
    interactive_mode = config.interactive_mode  # Boolean flag
```

#### `IReasoningConfig`
AI reasoning and generation parameters:

```python
from src.core.interfaces.configuration import IReasoningConfig

def apply_reasoning_settings(config: IReasoningConfig, request: dict):
    if config.reasoning_effort:
        request["reasoning_effort"] = config.reasoning_effort
    if config.temperature is not None:
        request["temperature"] = config.temperature
    if config.thinking_budget:
        request["thinking_budget"] = config.thinking_budget
```

#### `ILoopDetectionConfig`
Loop detection and prevention settings:

```python
from src.core.interfaces.configuration import ILoopDetectionConfig

def configure_loop_detection(config: ILoopDetectionConfig):
    if config.loop_detection_enabled:
        detector.enable()
        detector.set_pattern_range(
            config.min_pattern_length,
            config.max_pattern_length
        )
```

### Domain Models

The concrete implementations are immutable Pydantic models in `src/core/domain/configuration.py`:

#### `BackendConfig`
```python
from src.core.domain.configuration import BackendConfig

# Create configuration
config = BackendConfig(
    backend_type="openai",
    model="gpt-4",
    api_url="https://api.openai.com/v1",
    interactive_mode=True,
    failover_routes={"primary": {"backend": "openai", "model": "gpt-4"}}
)

# Modify configuration (creates new instance)
updated_config = config.with_model("gpt-3.5-turbo")
```

#### `ReasoningConfig`
```python
from src.core.domain.configuration import ReasoningConfig

config = ReasoningConfig(
    reasoning_effort="medium",
    thinking_budget=1000,
    temperature=0.7
)

# Chain modifications
updated_config = config.with_temperature(0.5).with_reasoning_effort("high")
```

#### `LoopDetectionConfig`
```python
from src.core.domain.configuration import LoopDetectionConfig

config = LoopDetectionConfig(
    loop_detection_enabled=True,
    tool_loop_detection_enabled=True,
    min_pattern_length=100,
    max_pattern_length=8000
)

# Update pattern length range
updated_config = config.with_pattern_length_range(50, 1000)
```

## Working with Configuration

### Creating Configuration Objects

Configuration objects are created using standard Pydantic model initialization:

```python
from src.core.domain.configuration import BackendConfig, ReasoningConfig

# Create with all parameters
backend_config = BackendConfig(
    backend_type="anthropic",
    model="claude-3-sonnet",
    api_url="https://api.anthropic.com",
    interactive_mode=True
)

# Create with defaults (most fields are optional)
reasoning_config = ReasoningConfig(temperature=0.8)
```

### Modifying Configuration

Since configuration objects are immutable, use the `with_*` methods to create modified copies:

```python
# Single modification
new_config = backend_config.with_model("claude-3-haiku")

# Multiple modifications
final_config = (backend_config
    .with_backend("openai")
    .with_model("gpt-4")
    .with_api_url("https://api.openai.com/v1"))
```

### Using Configuration in Services

Services should depend on configuration interfaces, not concrete classes:

```python
from src.core.interfaces.configuration import IBackendConfig, IReasoningConfig

class MyService:
    def __init__(
        self, 
        backend_config: IBackendConfig,
        reasoning_config: IReasoningConfig
    ):
        self._backend_config = backend_config
        self._reasoning_config = reasoning_config
    
    def process_request(self, request: dict) -> dict:
        # Use configuration to modify request
        if self._reasoning_config.temperature is not None:
            request["temperature"] = self._reasoning_config.temperature
        
        # Select backend based on configuration
        backend_type = self._backend_config.backend_type
        # ... rest of processing
```

## Configuration Loading

### Environment Variables

Configuration can be loaded from environment variables:

```bash
# Backend configuration
BACKEND_TYPE=openai
MODEL=gpt-4
API_URL=https://api.openai.com/v1

# Reasoning configuration
REASONING_EFFORT=medium
TEMPERATURE=0.7
THINKING_BUDGET=1000

# Loop detection configuration
LOOP_DETECTION_ENABLED=true
TOOL_LOOP_DETECTION_ENABLED=true
MIN_PATTERN_LENGTH=100
MAX_PATTERN_LENGTH=8000
```

### Configuration Files

Configuration can also be loaded from YAML or JSON files:

```yaml
# config.yaml
backend:
  backend_type: "openai"
  model: "gpt-4"
  api_url: "https://api.openai.com/v1"
  interactive_mode: true

reasoning:
  reasoning_effort: "medium"
  temperature: 0.7
  thinking_budget: 1000

loop_detection:
  loop_detection_enabled: true
  tool_loop_detection_enabled: true
  min_pattern_length: 100
  max_pattern_length: 8000
```

### Runtime Configuration

Configuration can be modified at runtime using commands:

```
!/set(backend=anthropic)
!/set(model=claude-3-sonnet)
!/set(temperature=0.8)
!/set(loop-detection=false)
```

## Dependency Injection

Configuration objects are registered with the dependency injection container:

```python
from src.core.di.services import get_service_collection
from src.core.interfaces.configuration import IBackendConfig
from src.core.domain.configuration import BackendConfig

# Register configuration
services = get_service_collection()
backend_config = BackendConfig(backend_type="openai", model="gpt-4")
services.add_instance(IBackendConfig, backend_config)

# Services can then depend on the interface
class MyService:
    def __init__(self, backend_config: IBackendConfig):
        self._config = backend_config
```

## Testing

Configuration objects are easy to test due to their immutable nature and interface-based design:

```python
import pytest
from src.core.domain.configuration import BackendConfig
from src.core.interfaces.configuration import IBackendConfig

def test_backend_config_creation():
    config = BackendConfig(
        backend_type="openai",
        model="gpt-4"
    )
    
    assert config.backend_type == "openai"
    assert config.model == "gpt-4"
    assert config.interactive_mode is True  # Default value

def test_backend_config_modification():
    original = BackendConfig(backend_type="openai", model="gpt-4")
    modified = original.with_model("gpt-3.5-turbo")
    
    # Original is unchanged
    assert original.model == "gpt-4"
    # New instance has the change
    assert modified.model == "gpt-3.5-turbo"
    # Other fields are preserved
    assert modified.backend_type == "openai"

def test_service_with_mock_config():
    # Create mock configuration
    mock_config = BackendConfig(
        backend_type="test",
        model="test-model"
    )
    
    # Use in service
    service = MyService(mock_config)
    result = service.process_request({})
    
    # Assert expected behavior
    assert result is not None
```

## Migration from Legacy Configuration

The system includes adapters to bridge legacy configuration with the new system:

### `LegacyConfigAdapter`

Wraps legacy configuration dictionaries to implement `IConfig`:

```python
from src.core.adapters.legacy_config_adapter import LegacyConfigAdapter

# Legacy configuration dictionary
legacy_config = {
    "backend": "openai",
    "model": "gpt-4",
    "temperature": 0.7
}

# Wrap with adapter
config_adapter = LegacyConfigAdapter(legacy_config)

# Use as IConfig interface
api_timeout = config_adapter.get("api_timeout", 30)
backend_type = config_adapter.backend_type
```

### Direct Service Provider Usage

With the migration complete, services now use the DI container directly:

```python
from src.core.di.services import get_service_provider

service_provider = get_service_provider()

# Use new configuration system directly
config = service_provider.get_required_service(IBackendConfig)
```

## Best Practices

1. **Always use interfaces** when depending on configuration in services
2. **Prefer immutable objects** over mutable dictionaries
3. **Use builder pattern** (`with_*` methods) for modifications
4. **Validate configuration early** at application startup
5. **Document configuration options** with clear descriptions and examples
6. **Test configuration objects** thoroughly, including edge cases
7. **Use dependency injection** to provide configuration to services
8. **Keep configuration focused** - separate concerns into different config objects

## Examples

### Complete Service Example

```python
from src.core.interfaces.configuration import IBackendConfig, IReasoningConfig
from src.core.domain.configuration import BackendConfig, ReasoningConfig

class ChatService:
    def __init__(
        self,
        backend_config: IBackendConfig,
        reasoning_config: IReasoningConfig
    ):
        self._backend_config = backend_config
        self._reasoning_config = reasoning_config
    
    async def process_chat(self, messages: list) -> dict:
        # Build request using configuration
        request = {
            "model": self._backend_config.model,
            "messages": messages
        }
        
        # Apply reasoning configuration
        if self._reasoning_config.temperature is not None:
            request["temperature"] = self._reasoning_config.temperature
        
        if self._reasoning_config.reasoning_effort:
            request["reasoning_effort"] = self._reasoning_config.reasoning_effort
        
        # Select backend and make request
        backend_type = self._backend_config.backend_type
        api_url = self._backend_config.api_url
        
        # ... make API call and return response

# Usage with dependency injection
def create_chat_service(service_provider):
    return ChatService(
        backend_config=service_provider.get_required_service(IBackendConfig),
        reasoning_config=service_provider.get_required_service(IReasoningConfig)
    )
```

### Configuration Builder Example

```python
from src.core.domain.configuration import BackendConfig, ReasoningConfig

def build_production_config():
    """Build configuration for production environment."""
    backend_config = (BackendConfig()
        .with_backend("openai")
        .with_model("gpt-4")
        .with_api_url("https://api.openai.com/v1")
        .with_interactive_mode(False))
    
    reasoning_config = (ReasoningConfig()
        .with_temperature(0.3)
        .with_reasoning_effort("high"))
    
    return backend_config, reasoning_config

def build_development_config():
    """Build configuration for development environment."""
    backend_config = (BackendConfig()
        .with_backend("openai")
        .with_model("gpt-3.5-turbo")
        .with_interactive_mode(True))
    
    reasoning_config = (ReasoningConfig()
        .with_temperature(0.8))
    
    return backend_config, reasoning_config
```

This configuration system provides a solid foundation for managing application settings in a type-safe, testable, and maintainable way.