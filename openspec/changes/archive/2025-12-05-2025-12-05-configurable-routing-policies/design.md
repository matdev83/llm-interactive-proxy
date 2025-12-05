# Design - Configurable Routing Policies

## Configuration Structure

We will add a new `routing` section to `AppConfig`:

```python
class RoutingConfig(DomainModel):
    disable_backend_ids: bool = False
    disable_backend_names: bool = False
    disable_model_names: bool = False
```

## Logic

The `BackendRoutingService` currently resolves backends in `resolve_backend_instance`. We will modify it to check these flags before proceeding with each resolution strategy.

1.  **Check Explicit Instance ID (Variant 1)**:
    -   If `backend_type` contains a dot (e.g., `openai.1`).
    -   Check if `disable_backend_ids` OR `disable_backend_names` is True.
    -   If disabled, raise `RoutingError` or return `None` (leading to fallback or error).

2.  **Check Generic Backend Name (Variant 2)**:
    -   If `backend_type` is provided but has no dot (e.g., `openai`).
    -   Check if `disable_backend_names` is True.
    -   If disabled, raise `RoutingError`.

3.  **Check Model Only (Variant 3)**:
    -   If `backend_type` is None.
    -   Check if `disable_model_names` is True.
    -   If disabled, raise `RoutingError`.

## Precedence Rules from Requirements
- `disable_routing_with_backend_names` implies `disable_routing_with_backend_ids`.
- `disable_routing_with_only_model_names` cannot be used together with any of the above? 
    - Requirement text: "cannot be used together with any of the above". 
    - This constraint implies mutual exclusivity. If "only model names" is disabled, the user MUST use backend names or IDs. If those are ALSO disabled, no routing is possible. 
    - However, the requirement specifically says: "disables automatic resolution of backend instances available for given model name, effectively requiring user to specify either backend name or backend name and instance ID".
    - So if I disable model names, I MUST allow backend names or IDs.
    - If I disable backend names (and thus IDs), I MUST allow model names.
    - So we should validate configuration to ensure at least one method remains valid.

## CLI Flags
- `--disable-routing-with-backend-ids` -> `routing.disable_backend_ids`
- `--disable-routing-with-backend-names` -> `routing.disable_backend_names`
- `--disable-routing-with-only-model-names` -> `routing.disable_model_names`

## Env Vars
- `DISABLE_ROUTING_WITH_BACKEND_IDS`
- `DISABLE_ROUTING_WITH_BACKEND_NAMES`
- `DISABLE_ROUTING_WITH_ONLY_MODEL_NAMES`
