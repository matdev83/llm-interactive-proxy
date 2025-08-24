# Application Factory API Reference

This document provides a reference for the Application Factory API, which is used to build and configure the FastAPI application for the LLM Interactive Proxy.

## Core Functions

### `build_app`

```python
def build_app(
    config: AppConfig | dict[str, Any] | None = None,
) -> tuple[FastAPI, AppConfig]:
```

Builds and configures the FastAPI application with the given configuration.

#### Parameters:
- `config`: The application configuration. Can be:
  - An `AppConfig` object
  - A dictionary of configuration values
  - `None` (will load from environment variables)

#### Returns:
- A tuple containing:
  - The configured FastAPI application
  - The normalized AppConfig object used to build the application

#### Example:
```python
from src.core.app.application_factory import build_app

# Build app with default configuration (from environment)
app, config = build_app()

# Build app with custom configuration
custom_config = AppConfig(host="localhost", port=9000)
app, config = build_app(config=custom_config)

# Build app with dictionary configuration
app, config = build_app(config={"host": "localhost", "port": 9000})
```

### `build_app_compat` (deprecated)

```python
def build_app_compat(
    config: AppConfig | dict[str, Any] | None = None,
) -> FastAPI:
```

**DEPRECATED**: Backward compatibility wrapper for legacy tests that expect only the FastAPI app. This function is maintained only for backward compatibility with existing tests and should not be used in new code. Prefer `build_app()` or `build_app_with_config()` in all new code.

#### Parameters:
- `config`: The application configuration (same as `build_app`)

#### Returns:
- The configured FastAPI application (without the config)

#### Example:
```python
from src.core.app.application_factory import build_app_compat  # deprecated

# Build app with default configuration (from environment)
app = build_app_compat()  # discouraged; prefer build_app()
```

## ApplicationBuilder Class

```python
class ApplicationBuilder:
```

The main builder class responsible for constructing and configuring the FastAPI application.

### Methods

#### `__init__`

```python
def __init__(self) -> None:
```

Initializes the application builder.

#### `build`

```python
def build(self, config: AppConfig) -> FastAPI:
```

Builds the FastAPI application with the given configuration.

##### Parameters:
- `config`: The application configuration (AppConfig object)

##### Returns:
- The configured FastAPI application

#### `_normalize_config`

```python
def _normalize_config(self, config: AppConfig) -> AppConfig:
```

Normalizes configuration shapes to ensure consistent types. This method ensures that all backend configurations are properly normalized to BackendConfig objects and that other configuration sections have consistent shapes.

##### Parameters:
- `config`: The application configuration to normalize

##### Returns:
- Normalized application configuration

#### `_initialize_services`

```python
async def _initialize_services(self, app: FastAPI, config: AppConfig) -> IServiceProvider:
```

Initializes services and registers them with the service provider.

##### Parameters:
- `app`: The FastAPI application
- `config`: The application configuration

##### Returns:
- The service provider with all services registered

#### `_initialize_backends`

```python
async def _initialize_backends(self, app: FastAPI, config: AppConfig) -> None:
```

Initializes backend services and registers them with the application.

##### Parameters:
- `app`: The FastAPI application
- `config`: The application configuration

## Migration Notes

The `build_app` function now returns a tuple `(app, config)` instead of just the app. If you're using `build_app` directly, you'll need to update your code to handle the new return type. For backward compatibility, you can use `build_app_compat` which returns only the app.

### Before:
```python
app = build_app()
```

### After:
```python
app, config = build_app()
```

### For legacy code only (not recommended):
```python
# DEPRECATED: Only for backward compatibility with existing tests
app = build_app_compat()
```
