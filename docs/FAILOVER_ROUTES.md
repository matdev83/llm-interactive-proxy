# Failover Routes

This document describes the failover route functionality in the LLM Interactive Proxy.

## Overview

Failover routes allow you to define fallback strategies when a backend or model is unavailable. Each route has a policy and a list of elements.

## Policies

The following failover policies are supported:

- `k` - Single backend, all keys: Try all API keys for the first backend:model in the route
- `m` - Multiple backends, first key: Try the first API key for each backend:model in the route
- `km` - All keys for all models: Try all API keys for each backend:model in the route
- `mk` - Round-robin keys across models: Try API keys in a round-robin fashion across all backend:model pairs

## Commands

The following commands are available for managing failover routes:

- `!/create-failover-route(name=<route>,policy=<policy>)` - Create a new failover route with the specified policy
- `!/delete-failover-route(name=<route>)` - Delete a failover route
- `!/list-failover-routes` - List all configured failover routes
- `!/route-list(name=<route>)` - List elements in a failover route
- `!/route-append(name=<route>,element=<backend:model>)` - Append an element to a failover route
- `!/route-prepend(name=<route>,element=<backend:model>)` - Prepend an element to a failover route
- `!/route-clear(name=<route>)` - Clear all elements from a failover route

## Examples

### Creating a Failover Route

```
!/create-failover-route(name=my-route,policy=k)
```

This creates a new failover route named "my-route" with the "k" policy.

### Adding Elements to a Route

```
!/route-append(name=my-route,element=openai:gpt-4)
!/route-append(name=my-route,element=anthropic:claude-3-opus)
```

This adds two elements to the route: "openai:gpt-4" and "anthropic:claude-3-opus".

### Listing Route Elements

```
!/route-list(name=my-route)
```

This lists all elements in the "my-route" route.

### Using a Failover Route

To use a failover route, set the model to the name of the route:

```
!/set(model=my-route)
```

Now, when you send a request, the proxy will try the backends and models defined in the route according to the policy.

## Implementation Details

The failover route functionality is implemented in the following components:

- `src/core/commands/handlers/failover_handlers.py` - Command handlers for managing failover routes
- `src/core/services/failover_service.py` - Service for implementing failover policies
- `src/core/domain/configuration/backend_config.py` - Domain model for backend configuration, including failover routes

The failover route functionality is fully integrated with the new SOLID architecture and follows the dependency inversion principle. The implementation is designed to be extensible, allowing for new policies to be added in the future.
