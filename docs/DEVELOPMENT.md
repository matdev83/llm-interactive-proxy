# llm-interactive-proxy: Intercepting Proxy for Dynamic Model Routing and More

## Project Goal

Create an intercepting proxy server for dynamic model routing, prompt/reply rewriting, and tool/custom app calling.

## Requirements

### Frontend Compatibility

*   **OpenAI API Compatible**: The proxy must expose a standard, fully functional HTTP API with all methods implemented, compatible with OpenAI's API. Specifically, it should support the `/v1/chat/completions` endpoint, allowing any client capable of setting a custom OpenAI API endpoint URL to use it. Potential future compatibility with other endpoints like `/v1/models` is implied.

### Backend Integration

The proxy is designed to integrate with various Large Language Model (LLM) APIs, providing a modular and extensible backend.

*   **Primary Integration**: Initially, the proxy will forward requests to the **OpenRouter API endpoint**.
*   **Modular Backend Support**: The architecture supports easy integration with multiple LLM APIs, including:
    *   **OpenAI Standard API**
    *   **OpenRouter API**
    *   **Google Gemini/AI Labs API**
*   **Extensibility**: The design allows for straightforward creation of new backend plugins to support additional LLM providers in the future.

### Core Functionality

*   **Dynamic Model Routing**:
    *   Clients specify a model in their requests.
    *   The proxy can override the requested model based on special commands.
    *   **Command `!/set(model=xxx/yyy)`**: Sets `xxx/yyy` as the override model for subsequent requests from that "session" (globally, for this simple proxy, unless explicit session management is added).
    *   **Command `!/unset(model)`**: Clears the active model override, restoring original routing behavior.
*   **Prompt/Reply Rewriting**:
    *   The framework should allow for general prompt/reply rewriting.
    *   Currently, the primary "rewriting" involves stripping proxy-specific commands from the prompt before forwarding to the LLM backend.
*   **Command Handling**:
    *   Commands are identified by starting with `!/`.
    *   They are parsed from the user's prompt.
    *   They modify the proxy's behavior.
    *   **Crucially, recognized proxy-specific commands are NOT sent to the LLM backend.**
*   **Multimodal Support**:
    *   The proxy must handle multimodal user prompts, including images, documents, custom files, sound, etc.
    *   These multimodal parts (typically base64 encoded data URIs for images in content arrays, as per OpenAI API message format) must be passed "as-is" to the remote OpenRouter API endpoint.
*   **Response Handling**:
    *   All responses from OpenRouter, including streaming responses and those containing streamed thinking/reasoning output, must be proxied back to the client as-is.

### Technical Requirements

*   **Language**: Python.
*   **Logging**: Use a standard Python logging framework (e.g., the built-in `logging` module).
*   **Debugging**: Generate verbose debug messages to the console to ease the development process. Debugging output should not be part of the HTTP output.
*   **Web Server Framework**: A web server framework like FastAPI or Flask will be needed to handle incoming HTTP requests. FastAPI is generally preferred for its async capabilities and Pydantic integration, which is well-suited for OpenAI-like APIs.
*   **HTTP Client Library**: An HTTP client library (like `httpx`) will be required to make asynchronous requests to OpenRouter, especially for handling streaming responses.
*   **Logic Components**:
    *   Logic to parse commands from user prompts.
    *   State management (even if simple/global for now) for the `override_model`.
    *   Careful handling of request/response bodies, particularly for streaming and multimodal content.
*   **Source File Structure**:
    *   Files exceeding 250 lines of code should be structurally split into smaller, more manageable files.
    *   This splitting must ensure a uniform API design and proper encapsulation of the internal file structure, maintaining a clear and consistent interface for external modules.
*   **Programming Paradigm**: Object-Oriented Programming (OOP) should be used for structuring the codebase.
*   **Architectural Style**: An Event-Driven Architecture (EDA) should be employed where appropriate to handle asynchronous operations and decouple components.
*   **Modularity**: The design must facilitate easy addition of new commands, functions, or features exposed by the server without requiring major refactoring of existing code.
*   **Coupling**: Components should exhibit loose coupling to enhance flexibility, maintainability, and testability.
*   **Design Principles**: Adhere to DRY (Don't Repeat Yourself) and KISS (Keep It Simple, Stupid) principles throughout the development process.
*   **Code Documentation**: Every function, method, and class must include a short, clear description of its purpose and functionality.
*   **Testing Flexibility**: Tests should support both true remote/network I/O for integration testing and mocked I/O for unit testing, ensuring comprehensive test coverage.
*   **Network Binding**: By default, the proxy should bind only to the `127.0.0.1` (localhost) IP address to prevent unintended external network access.
*   **Streaming API Support**: The proxy must fully support streaming API capabilities for both the client-facing interface and the remote LLM API backend.
*   **Custom Model Parameters**: Support for passing custom model parameters/settings (e.g., `temperature`, `sampling`, `reasoning effort`, `number of allowed reasoning tokens`) from the client to the remote LLM API.
*   **Configurable Timeouts**: Implement configurable timeouts for all communications with remote LLM APIs to prevent indefinite waits and improve resilience.
*   **Modular LLM Backend Support**:
    *   Provide modular support for different LLM APIs/backends, including:
        *   OpenAI standard
        *   OpenRouter
        *   Google Gemini/AI Labs
    *   Ensure an easy way to create new backend plugins for future LLM integrations.
    ```mermaid
    graph TD
        A[Proxy Server] --> B{LLM Backend Router};
        B --> C1[OpenAI Backend Plugin];
        B --> C2[OpenRouter Backend Plugin];
        B --> C3[Google Gemini/AI Labs Backend Plugin];
        B --> C4[Custom Backend Plugin (Easy to Add)];

        C1 --> D1[OpenAI API];
        C2 --> D2[OpenRouter API];
        C3 --> D3[Google Gemini API];
        C4 --> D4[Other LLM API];

        subgraph LLM Backend Plugins
            C1
            C2
            C3
            C4
        end
    ```

## Key Functions to be Implemented

*   **Model Routing**: Implement robust model routing logic based on interactive commands sent by the user within their prompts.
*   **Google AI/Gemini API Key Failover**: Develop a mechanism for API key failover specifically for Google AI/Gemini backends to ensure continuous service in case of key limitations or issues.
*   **Diff/File Edit Response Repair Module**: Implement a module designed to analyze LLM responses containing file edits or diffs. This module will leverage knowledge of local files to attempt to fix or refine the remote LLM's output 'on-the-fly' before it is forwarded to the calling client, addressing common LLM struggles with precise code generation.
    ```mermaid
    sequenceDiagram
        participant LLMBackend
        participant ProxyServer
        participant RepairModule
        participant ClientApp

        LLMBackend->>ProxyServer: LLM Response (potentially with diff/edit)
        ProxyServer->>RepairModule: Forward response for analysis
        RepairModule->>RepairModule: Analyze response for diff/edit patterns
        RepairModule->>RepairModule: Access local file knowledge (if needed)
        RepairModule-->>ProxyServer: Repaired/Refined Response
        ProxyServer-->>ClientApp: Final Response
    ```

## User Stories

Here are some key user stories for the proxy server:

```mermaid
graph TD
    A[User] --> B{Wants to use a specific LLM model};
    B --> C{Sends prompt to Proxy};
    C --> D{Proxy checks for !/set(model=...) command};
    D -- Yes --> E[Proxy overrides model for subsequent requests];
    D -- No --> F[Proxy uses model from client request];
    E --> G[Proxy forwards prompt to OpenRouter with overridden model];
    F --> G;
    G --> H[OpenRouter processes prompt];
    H --> I[OpenRouter sends response to Proxy];
    I --> J[Proxy forwards response to User];
```

```mermaid
sequenceDiagram
    participant ClientApp
    participant ProxyServer
    participant OpenRouterAPI

    ClientApp->>ProxyServer: POST /v1/chat/completions (prompt: "Hello, world!", model: "gpt-3.5-turbo")
    ProxyServer->>OpenRouterAPI: POST /v1/chat/completions (prompt: "Hello, world!", model: "gpt-3.5-turbo")
    OpenRouterAPI-->>ProxyServer: Streaming Response
    ProxyServer-->>ClientApp: Streaming Response

    ClientApp->>ProxyServer: POST /v1/chat/completions (prompt: "!/set(model=custom/model-v2) What is the weather?")
    ProxyServer->>ProxyServer: Parse command, set override_model="custom/model-v2"
    ProxyServer->>OpenRouterAPI: POST /v1/chat/completions (prompt: "What is the weather?", model: "custom/model-v2")
    OpenRouterAPI-->>ProxyServer: Response
    ProxyServer-->>ClientApp: Response

    ClientApp->>ProxyServer: POST /v1/chat/completions (prompt: "Tell me a story.", model: "gpt-4")
    ProxyServer->>ProxyServer: Check override_model (is "custom/model-v2")
    ProxyServer->>OpenRouterAPI: POST /v1/chat/completions (prompt: "Tell me a story.", model: "custom/model-v2")
    OpenRouterAPI-->>ProxyServer: Streaming Response
    ProxyServer-->>ClientApp: Streaming Response

    ClientApp->>ProxyServer: POST /v1/chat/completions (prompt: "!/unset(model) What is the capital of France?")
    ProxyServer->>ProxyServer: Parse command, clear override_model
    ProxyServer->>OpenRouterAPI: POST /v1/chat/completions (prompt: "What is the capital of France?", model: "gpt-4")
    OpenRouterAPI-->>ProxyServer: Response
    ProxyServer-->>ClientApp: Response
```

## Architecture

This project will be developed as a modern Python application, utilizing a layered, modular design to ensure maintainability, scalability, and testability.

Whenever possible, Test-Driven Development (TDD) will be employed. This means that for any given function or feature, the agent implementing it **MUST** first write the tests that define its expected behavior. If there is any ambiguity or lack of clarity regarding the testing requirements or specific test cases, the agent **MUST** brief the user to obtain all necessary answers before proceeding with implementation.

The expected architectural flow is as follows:

```mermaid
graph LR
    A[Client Application] --> B(Our Proxy Server);
    B -- Checks for special commands (!/) --> C{Command Logic};
    C -- If command, modifies behavior --> B;
    B -- Otherwise, forwards prompt --> D[Remote LLM API (OpenRouter)];
    D -- Generates response (including streaming/media) --> B;
    B -- Forwards response --> A;

    subgraph Proxy Internal Components
        B -- Uses --> E[Web Server Framework (e.g., FastAPI)];
        B -- Uses --> F[HTTP Client Library (e.g., httpx)];
        B -- Manages --> G[Override Model State];
        B -- Handles --> H[Multimodal Content Parsing];
        B -- Utilizes --> I[Standard Python Logging];
    end
