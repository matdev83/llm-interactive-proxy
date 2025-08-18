# Dependency Injection Container Usage Patterns

## Overview

This document describes the recommended patterns for using the Dependency Injection (DI) container in the LLM Interactive Proxy application. The DI container is a central component that manages service instantiation, lifetime, and dependencies.

## Service Registration Order

When registering services in the DI container, it's important to follow the correct order to ensure dependencies are available when needed:

1. **Register dependencies before dependents**
   - Example: Register `BackendRegistry` before `BackendFactory` since the factory depends on the registry
   - Example: Register `httpx.AsyncClient` before services that use it

2. **Register interfaces after concrete implementations**
   - Example: Register `BackendService` first, then register `IBackendService` with the same factory function
   - This ensures that both interface and concrete type requests resolve to the same singleton instance

## Service Lifetime Management

The DI container supports three service lifetimes:

1. **Singleton**: One instance for the entire application
   - Use for stateful services that should be shared across the application
   - Example: `BackendRegistry`, `BackendFactory`, `BackendService`

2. **Scoped**: One instance per scope (request)
   - Use for services that should be isolated per request but shared within a request
   - Example: Request-specific state, transaction contexts

3. **Transient**: New instance each time requested
   - Use for stateless services or when a fresh instance is needed each time
   - Example: Value objects, DTOs, utility classes

## Registration Methods

### Direct Type Registration

```python
# Register a singleton service with its default constructor
services.add_singleton(BackendRegistry)

# Register a transient service
services.add_transient(MyUtilityClass)
```

### Factory Function Registration

```python
# Register a service with a factory function
def _backend_factory(provider: IServiceProvider) -> BackendFactory:
    client = provider.get_required_service(httpx.AsyncClient)
    registry = provider.get_required_service(BackendRegistry)
    return BackendFactory(client, registry)

services.add_singleton(BackendFactory, implementation_factory=_backend_factory)
```

### Interface Registration

```python
# Register an interface with a concrete implementation
services.add_singleton(IBackendService, BackendService)

# Register an interface with the same factory as its implementation
services.add_singleton(IBackendService, implementation_factory=_backend_service_factory)
```

### Instance Registration

```python
# Register an existing instance
services.add_instance(BackendRegistry, backend_registry)
```

## Service Resolution

### Basic Resolution

```python
# Get a service (returns None if not registered)
service = provider.get_service(IBackendService)

# Get a required service (throws if not registered)
service = provider.get_required_service(IBackendService)

# Get a required service with a default factory
service = provider.get_required_service_or_default(
    IBackendService,
    lambda: BackendService(default_dependencies)
)
```

### Scoped Resolution

```python
# Create a scope
scope = provider.create_scope()

# Get a scoped service
with scope:
    service = scope.service_provider.get_service(IScopedService)
```

## Best Practices

1. **Register services at application startup**
   - All services should be registered in `ApplicationBuilder._initialize_services`
   - Avoid registering services after the application has started

2. **Use interfaces for dependencies**
   - Depend on interfaces rather than concrete implementations
   - This makes it easier to swap implementations and mock for testing

3. **Prefer constructor injection**
   - Pass dependencies through constructors rather than using service locator pattern
   - This makes dependencies explicit and easier to test

4. **Use factory functions for complex initialization**
   - When a service has complex initialization logic or multiple dependencies
   - Factory functions can handle conditional logic and error handling

5. **Handle missing services gracefully**
   - Use `get_required_service_or_default` for optional dependencies
   - Provide sensible defaults when services are missing

6. **Avoid circular dependencies**
   - Design services to avoid circular dependencies
   - If necessary, use factories or providers to break cycles

## Common Pitfalls

1. **Incorrect registration order**
   - Registering a service before its dependencies
   - Solution: Register dependencies first

2. **Missing interface registrations**
   - Forgetting to register an interface after registering its implementation
   - Solution: Always register both interface and implementation

3. **Inconsistent singleton instances**
   - Registering a service as both concrete type and interface with different factories
   - Solution: Use the same factory for both registrations

4. **Scoped service resolution from root provider**
   - Trying to resolve a scoped service from the root provider
   - Solution: Always resolve scoped services from a scope

5. **Service provider leakage**
   - Passing the service provider to services
   - Solution: Use constructor injection instead

## Example: Controller Registration

```python
# Register a controller with its dependencies
def _chat_controller_factory(provider: IServiceProvider) -> ChatController:
    request_processor = provider.get_required_service(IRequestProcessor)
    return ChatController(request_processor)

services.add_singleton(ChatController, implementation_factory=_chat_controller_factory)
```

## Example: Robust Service Resolution

```python
# Robust service resolution with fallbacks
factory = service_provider.get_required_service_or_default(
    BackendFactory,
    lambda: BackendFactory(
        service_provider.get_required_service_or_default(
            httpx.AsyncClient, 
            httpx.AsyncClient
        ),
        service_provider.get_required_service_or_default(
            BackendRegistry, 
            lambda: backend_registry
        )
    )
)
```
