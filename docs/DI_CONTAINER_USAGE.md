# Dependency Injection Container Usage Guide

This document provides a guide to using the Dependency Injection (DI) container in the LLM Interactive Proxy application.

## Overview

The application uses a DI container to manage service dependencies and promote loose coupling between components. This approach follows the Dependency Inversion Principle (DIP) from SOLID principles, allowing high-level modules to depend on abstractions rather than concrete implementations.

## Core Components

### IServiceProvider

The `IServiceProvider` interface defines the contract for resolving services from the DI container:

```python
class IServiceProvider(Protocol):
    def get_service(self, service_type: type[T]) -> T | None: ...
    def get_required_service(self, service_type: type[T]) -> T: ...
```

### ServiceCollection

The `ServiceCollection` class is used to register services with the DI container:

```python
class ServiceCollection:
    def add_singleton(self, service_type: type[T], implementation_type: type[T] | None = None) -> None: ...
    def add_singleton_factory(self, service_type: type[T], factory: Callable[[IServiceProvider], T]) -> None: ...
    def add_instance(self, service_type: type[T], instance: T) -> None: ...
    def build_service_provider(self) -> IServiceProvider: ...
```

## Service Registration

### Singleton Registration

Singleton services are registered once and reused throughout the application:

```python
# Register a service with its implementation
services.add_singleton(ISessionService, SessionService)

# Register a service with itself as the implementation
services.add_singleton(BackendRegistry)

# Register a service with a factory function
services.add_singleton_factory(IBackendService, backend_service_factory)
```

### Instance Registration

Pre-created instances can be registered directly:

```python
# Register a pre-created instance
shared_httpx_client = httpx.AsyncClient()
services.add_instance(httpx.AsyncClient, shared_httpx_client)
```

### Factory Registration

Services that require complex initialization or dependencies can be registered with factory functions:

```python
def backend_service_factory(provider: IServiceProvider) -> BackendService:
    httpx_client = provider.get_required_service(httpx.AsyncClient)
    backend_registry = provider.get_required_service(BackendRegistry)
    backend_factory = BackendFactory(httpx_client, backend_registry)
    rate_limiter = provider.get_required_service(RateLimiter)
    app_config = provider.get_required_service(AppConfig)
    backend_config_provider = BackendConfigProvider(app_config)
    
    return BackendService(
        backend_factory,
        rate_limiter,
        app_config,
        backend_config_provider=backend_config_provider,
    )

services.add_singleton_factory(IBackendService, backend_service_factory)
```

## Service Resolution

### Getting Services

Services can be resolved from the container in several ways:

```python
# Get a service (returns None if not registered)
backend_service = provider.get_service(IBackendService)

# Get a required service (raises exception if not registered)
backend_service = provider.get_required_service(IBackendService)
```

### FastAPI Dependency Injection

Services can be injected into FastAPI endpoints using the `Depends` function:

```python
def get_backend_service(request: Request) -> IBackendService:
    return request.app.state.service_provider.get_required_service(IBackendService)

@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    chat_request: ChatRequest,
    backend_service: IBackendService = Depends(get_backend_service),
):
    # Use backend_service here
    ...
```

## Startup Sequence

The application's DI container is initialized during startup in the following sequence:

1. **Create ServiceCollection**: `services = get_service_collection()`
2. **Register Core Services**:
   - `httpx.AsyncClient` (shared instance)
   - `AppConfig`
   - `BackendRegistry`
   - `RateLimiter`
   - `LoopDetector`
   - `FailoverService`
3. **Register Service Factories**:
   - `BackendFactory`
   - `BackendService`
   - `CommandService`
   - `SessionService`
   - `RequestProcessor`
   - `ResponseProcessor`
4. **Build Service Provider**: `provider = services.build_service_provider()`
5. **Store on app.state**: `app.state.service_provider = provider`
6. **Initialize Backends**: `await builder._initialize_backends(app, config)`

## Key Services and Their Dependencies

### BackendService

- **Dependencies**:
  - `BackendFactory`
  - `RateLimiter`
  - `AppConfig`
  - `BackendConfigProvider`

### BackendFactory

- **Dependencies**:
  - `httpx.AsyncClient`
  - `BackendRegistry`

### RequestProcessor

- **Dependencies**:
  - `IBackendService`
  - `ISessionService`
  - `ICommandService`

### ResponseProcessor

- **Dependencies**:
  - `LoopDetector`

## Best Practices

### 1. Depend on Interfaces, Not Implementations

```python
# Good
def __init__(self, backend_service: IBackendService):
    self._backend_service = backend_service

# Avoid
def __init__(self, backend_service: BackendService):
    self._backend_service = backend_service
```

### 2. Use Factory Functions for Complex Initialization

```python
def backend_service_factory(provider: IServiceProvider) -> BackendService:
    # Get dependencies from the provider
    httpx_client = provider.get_required_service(httpx.AsyncClient)
    # ...
    return BackendService(...)
```

### 3. Register Shared Resources as Singletons

```python
# Create a single shared httpx.AsyncClient instance
shared_httpx_client = httpx.AsyncClient()
services.add_instance(httpx.AsyncClient, shared_httpx_client)
```

### 4. Use Type Casting for Interface Registration

```python
# Register a service with an interface
services.add_singleton(cast(type, IBackendService), implementation_factory=backend_service_factory)
```

### 5. Ensure Proper Shutdown of Resources

```python
@app.on_event("shutdown")
async def shutdown_handler() -> None:
    # Close shared httpx client
    client = getattr(app.state, "httpx_client", None)
    if client is not None and isinstance(client, httpx.AsyncClient):
        await client.aclose()
```

## Testing with DI

### Mocking Services

```python
def test_backend_service():
    # Create mock dependencies
    mock_factory = MagicMock(spec=BackendFactory)
    mock_rate_limiter = MagicMock(spec=RateLimiter)
    mock_config = MagicMock(spec=AppConfig)
    mock_config_provider = MagicMock(spec=IBackendConfigProvider)
    
    # Create service with mock dependencies
    service = BackendService(
        mock_factory,
        mock_rate_limiter,
        mock_config,
        backend_config_provider=mock_config_provider,
    )
    
    # Test the service
    # ...
```

### Using Test Service Provider

```python
def test_with_service_provider():
    # Create test service collection
    services = ServiceCollection()
    
    # Register mock services
    mock_backend_service = MagicMock(spec=IBackendService)
    services.add_instance(IBackendService, mock_backend_service)
    
    # Build service provider
    provider = services.build_service_provider()
    
    # Get service from provider
    backend_service = provider.get_required_service(IBackendService)
    assert backend_service is mock_backend_service
```

## Common Issues and Solutions

### 1. Service Not Found

If `get_required_service` raises an exception:

- Check that the service is registered in `_initialize_services`
- Verify the service type matches exactly (including generics)
- Check for circular dependencies

### 2. Wrong Implementation

If the wrong implementation is returned:

- Check that the service is registered with the correct implementation
- Verify that the service is not overridden elsewhere
- Check for multiple registrations of the same service type

### 3. Circular Dependencies

If you encounter circular dependencies:

- Refactor to break the cycle
- Use factory functions to defer initialization
- Consider using events or message passing instead of direct dependencies