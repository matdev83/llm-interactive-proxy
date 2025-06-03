# OpenAI Compatible Intercepting Proxy Server

This project provides an intercepting proxy server that is compatible with the OpenAI API. It allows for modification of requests and responses, command execution within chat messages, and model overriding. It currently uses OpenRouter.ai as its backend.

## Features

- **OpenAI API Compatibility**: Acts as a drop-in replacement for OpenAI API endpoints like `/v1/chat/completions` and `/v1/models`.
- **Request/Response Interception**: (Currently focused on request modification)
- **Command System**: Process special commands in user messages (e.g., `!/set(model=claude-3-opus-20240229)` to change the target model).
- **Model Override**: Dynamically change the LLM model used for requests via commands.
- **OpenRouter Backend**: Leverages OpenRouter.ai to access a wide variety of LLMs.
- **Streaming and Non-Streaming Support**: Handles both types of chat completion requests.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

- Python 3.8+
- `pip` for installing Python packages

### Installation

1.  **Clone the repository (if you haven't already):**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Create a `.env` file:**
    Copy the example environment variables or create a new `.env` file in the project root:
    ```env
    OPENROUTER_API_KEY="your_openrouter_api_key_here"
    # PROXY_HOST="0.0.0.0"  # Optional: Default is 0.0.0.0
    # PROXY_PORT="8000"      # Optional: Default is 8000
    # APP_SITE_URL="http://localhost:8000" # Optional: Used for HTTP-Referer header
    # APP_X_TITLE="MyProxy"              # Optional: Used for X-Title header
    ```
    Replace `"your_openrouter_api_key_here"` with your actual OpenRouter API key.

4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Install development dependencies (for running tests and development):**
    ```bash
    pip install -r requirements-dev.txt
    ```

### Running the Proxy Server

To start the proxy server, run the `main.py` script from the `src` directory:

```bash
python src/main.py
```

The server will typically start on `http://0.0.0.0:8000` (or as configured in your `.env` file). You should see log output indicating the server has started, e.g.:
`INFO:     Started server process [xxxxx]`
`INFO:     Waiting for application startup.`
`INFO:     Application startup complete.`
`INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)`

### Running Tests

To run the automated tests, use pytest:

```bash
pytest
```

Ensure you have installed the development dependencies (`requirements-dev.txt`) before running tests.

## Usage

Once the proxy server is running, you can configure your OpenAI-compatible client applications to point to the proxy's address (e.g., `http://localhost:8000/v1`) instead of the official OpenAI API base URL.

### Command Feature

You can embed special commands within your chat messages to control the proxy's behavior. The primary command currently supported is:

-   `!/set(model=model_name)`: Overrides the model for the current session/request.
    Example: `Hello, please use !/set(model=mistralai/mistral-7b-instruct) for this conversation.`
-   `!/unset(model)`: Clears any previously set model override.

The proxy will process these commands, strip them from the message sent to the LLM, and adjust its behavior accordingly.

## Project Structure

```
.
├── src/                  # Source code
│   ├── connectors/       # Backend connectors (OpenRouter, etc.)
│   ├── main.py           # FastAPI application, endpoints
│   ├── models.py         # Pydantic models for API requests/responses
│   └── proxy_logic.py    # Core logic for command parsing, state management
├── tests/                # Automated tests
│   ├── integration/
│   └── unit/
├── .env.example          # Example environment variables (optional, if not in README)
├── .gitignore
├── README.md             # This file
├── requirements.txt      # Main application dependencies
├── requirements-dev.txt  # Development and test dependencies
└── pyproject.toml        # Project metadata, build system config
```

## Contributing

Please refer to `docs/DEVELOPMENT.md` for details on the development process, style guides, and how to contribute. (Note: `docs/DEVELOPMENT.md` was mentioned in a previous subtask's `ls` output).
