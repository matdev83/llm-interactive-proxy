# Plugin API

This guide describes the supported plugin contract for external backend packages.
Use this API when publishing backends through Python entry points instead of
adding connectors directly in `src/connectors/`.

## Entry-point contract

- **Entry-point group**: `llm_proxy_backends`
- **Provider callable**: must return `BackendPluginDefinition`
- **Discovery mode**: fail-open (`missing`, `broken`, or `incompatible` plugins
  are skipped with warnings and core startup continues)

The supported API is exported from `src/core/plugin_api.py`:

- `BACKEND_PLUGIN_ENTRY_POINT_GROUP`
- `PluginCompatibility`
- `BackendPluginDefinition`
- `BackendPluginProvider`
- `PluginPostBuildHook` (optional)

## Required definition fields

`BackendPluginDefinition` must include:

- `backend_name`: canonical backend key
- `factory`: backend factory callable returning a core-compatible backend instance
- `plugin_name`: package/plugin identifier for diagnostics
- `compatibility`: `PluginCompatibility(core_min_version, core_max_version=None)`

Optional:

- `post_build_hook`: `PluginPostBuildHook` called after DI provider build for
  successfully registered compatible plugins only.

### Factory call contract

`BackendPluginDefinition.factory` is registered in `BackendRegistry` and invoked by
core backend creation with positional arguments:

1. `httpx.AsyncClient`
2. `AppConfig`
3. `translation_service`

Plugin factories should accept this call shape (or a compatible `*args, **kwargs`
signature) and return a backend instance without performing network I/O
during construction.

## Compatibility behavior

- `core_min_version` is required.
- `core_max_version` is optional.
- Incompatible plugins are skipped with warning and do not fail startup.

## Registration hook behavior

`post_build_hook` is optional and must be callable.

- Executed after core post-build actions.
- Executed only for plugins that passed compatibility checks and were registered.
- Exceptions inside a hook are logged as warnings and ignored (fail-open).

## Minimal plugin package example

`pyproject.toml`:

```toml
[project.entry-points."llm_proxy_backends"]
my-backend = "my_plugin.providers:my_backend"
```

`providers.py`:

```python
from src.core.plugin_api import (
    BackendPluginDefinition,
    PluginCompatibility,
)


def my_backend() -> BackendPluginDefinition:
    return BackendPluginDefinition(
        backend_name="my-backend",
        factory=_build_backend,
        plugin_name="my-plugin-package",
        compatibility=PluginCompatibility(core_min_version="0.1.0"),
    )
```

## Configuration expectations

- Backends are referenced by `backend_name` in runtime config (`default_backend`,
  `static_route`, or named backend instances).
- If a config references an extracted backend that is not installed, startup and
  request-time diagnostics include install guidance:
  `pip install llm-interactive-proxy[oauth]`.

## Reference implementation

- Example plugin package repo: `https://github.com/matdev83/llm-proxy-oauth-connectors`
- Provider implementations:
  `src/llm_proxy_oauth_connectors/providers.py`
