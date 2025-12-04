# Proposal: Refactor Backend Connectors

## Summary
Decouple backend connector implementations (code) from runtime backend instances (configuration). This allows configuring multiple instances of the same backend provider, each with distinct credentials, base URLs, concurrency settings, and supported input types. The proposal distinguishes between **API Key Backends** and **Credential File Backends**, and implements **Instance Rotation/Load Balancing** to preserve and enhance API key rotation capabilities.

## Motivation
The current 1:1 mapping between connector implementations and backend instances limits flexibility. Key drivers include:
-   **API Key Rotation**: Distributing traffic across multiple keys (via multiple instances).
-   **Cross-Account Rotation**: Using multiple provider accounts (OAuth or API key) for redundancy.
-   **Concurrency Control**: Enforcing limits on specific accounts (e.g., free tier).
-   **Custom Endpoints**: Targeting different environments.
-   **Multimodal Capability Control**: defining exactly what input types (images, PDFs) a specific instance supports.

## Proposed Changes
1.  **Naming Convention**: Enforce `<connector-name>.<unique-instance-name>`.
2.  **Configuration Schema**:
    -   `allow_concurrent_use` (bool).
    -   Credentials (API key or path).
    -   `api_url` override.
    -   `supported_input_types` (list of types like `image/jpeg`, `application/pdf`).
3.  **Connector Classification**:
    -   Explicitly categorize connectors as either "API Key based" or "Credential File based".
4.  **Global Multimodal Registry**:
    -   A central dictionary defining all known multimodal input types.
5.  **Automated Instance Creation**:
    -   **API Key Backends**: Discover via `ENV_VAR_N`.
    -   **Credential File Backends**: Discover via existence of `config/backends/backend-instances/<connector>.<name>.yaml`.
    -   **Fallback (File-based only)**: If no configs found, create default `<connector>.1`.
6.  **Validation**:
    -   Enforce uniqueness of credential file paths per connector type (File-based only).
7.  **Instance Rotation / Load Balancing**:
    -   Implement Round Robin rotation across multiple instances of the same connector type when a generic backend is requested (e.g., `openrouter` request rotates between `openrouter.1`, `openrouter.2`).
8.  **Instance Rotation / Load Balancing**:
    -   Implement Round Robin rotation across multiple instances of the same connector type.
    -   **Automated Resolution**: Automatically resolve generic backend names (e.g., `gemini`) to concrete instances (`gemini.1`, `gemini.2`) to support backward compatibility.
9.  **Granular Rate Limiting**:
    -   Track availability at two levels: **Instance-wide** and **Model-specific**.
    -   Use absolute timestamps (`available_after`) for precise reset handling.
    -   Ensure model-specific limits do not block other models on the same instance.
10. **Instance Management**:
    -   Strict concurrency checks.
11. **Model-Centric Routing**:
    -   Allow requests using only model names (e.g., `gemini-2.5-pro`, `google/gemini-2.5-pro`).
    -   Automatically resolve to the best available backend instance supporting that model.
    -   Global model registry to map `model_name -> list[instance_name]`.

## Risks & Mitigation
-   **Backward Compatibility**: Support legacy names.
-   **Config Conflicts**: Explicit precedence rules (Config File > Defaults).
