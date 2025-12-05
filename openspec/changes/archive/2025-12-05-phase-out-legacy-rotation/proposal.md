# Proposal: Phase Out Legacy API Key Rotation

## Background
The system currently contains legacy code and configuration logic designed for an older API key rotation strategy where a single backend connector instance would cycle through a list of API keys. This approach has been superseded by a new architecture based on multiple backend instances (e.g., `openai.1`, `openai.2`) which are routed via the service layer (Round Robin). The legacy code aggregates numbered environment variables into a list but then effectively ignores all but the first one at runtime, causing confusion and potential misconfiguration.

## Goal
To completely remove the legacy API key rotation implementation in favor of the new multi-instance backend architecture. This involves cleaning up configuration loading logic, removing unused attributes in connector classes, updating documentation, and ensuring no legacy interactive commands or variables remain.

## Scope
-   **Configuration Loading**: Update `AppConfig` to stop aggregating numbered env vars (e.g., `OPENAI_API_KEY_N`) into a list for the *primary* backend config. These env vars are already handled correctly by `BackendSettings` discovery.
-   **Backend Config Model**: Change `BackendConfig.api_key` from `list[str]` to `str | None`.
-   **Connectors**: Remove `self.api_keys` list attributes from connector implementations.
-   **Commands**: Ensure no commands rely on `api_keys` list or legacy rotation strategy.
-   **Documentation**: Update user guides to reflect the new multi-instance rotation method and remove references to the legacy method.

## Risks
-   **Breaking Change**: Users who *might* be relying on the `api_keys` list in `AppConfig` for some custom extension (though unlikely as it's not used by core connectors) will see a change in type.
-   **Configuration Compatibility**: Existing `config.yaml` files that might provide `api_key` as a list (if supported by schema) will need to be handled or migrated (schema validation should catch this).
