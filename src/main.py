import logging
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime # Needed for command-only response timestamp
from typing import Union, Dict, Any, Callable # Import Union, Dict, Any, Callable for response_model and headers

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

import src.models as models  # Import the models module directly
from src.proxy_logic import process_commands_in_messages, ProxyState  # Import process_commands_in_messages and ProxyState class
from src.connectors.openrouter import OpenRouterBackend  # Import the backend used in tests

# --- Configuration ---
# Load environment variables from .env file
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_BASE_URL = os.getenv("OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1")
APP_SITE_URL = os.getenv("APP_SITE_URL", "http://localhost:8000") # Used for Referer header
APP_X_TITLE = os.getenv("APP_X_TITLE", "InterceptorProxy")     # Used for X-Title header
PROXY_PORT = int(os.getenv("PROXY_PORT", "8000"))
PROXY_HOST = os.getenv("PROXY_HOST", "0.0.0.0")
OPENROUTER_TIMEOUT = int(os.getenv("OPENROUTER_TIMEOUT", "300")) # 5 minutes

# Function to build headers for OpenRouter requests
def get_openrouter_headers() -> Dict[str, str]:
    """Return headers required for OpenRouter requests."""
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}" if OPENROUTER_API_KEY else "",
        "Content-Type": "application/json",
        "HTTP-Referer": APP_SITE_URL,
        "X-Title": APP_X_TITLE,
    }

# --- Logging Setup ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

if not OPENROUTER_API_KEY:
    logger.critical("OPENROUTER_API_KEY is not set. The proxy will not be able to connect to OpenRouter.")

# --- HTTP Client Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the lifecycle of the FastAPI application.
    Initializes resources like the HTTPX client and backend connectors on startup,
    and ensures they are cleaned up properly on shutdown.
    """
    # Startup: Initialize the HTTP client, backend connector, and proxy state
    logger.info("Application startup: Initializing HTTPX client.")
    client = httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT)
    app.state.httpx_client = client
    openrouter_backend = OpenRouterBackend(client)
    app.state.openrouter_backend = openrouter_backend
    app.state.proxy_state = ProxyState()  # Initialize and store ProxyState in app.state
    if not OPENROUTER_API_KEY:
        logger.warning(
            "OPENROUTER_API_KEY is not configured. Requests to OpenRouter will likely fail."
        )
    yield
    # Shutdown: Close the HTTP client
    logger.info("Application shutdown: Closing HTTPX client.")
    await client.aclose()

app = FastAPI(lifespan=lifespan)


# --- API Endpoints ---
@app.get("/")
async def root():
    """Provides a simple welcome message indicating the server is running."""
    logger.info("Root endpoint '/' accessed.")
    return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

@app.post("/v1/chat/completions", response_model=Union[models.CommandProcessedChatCompletionResponse, Dict[str, Any]])
async def chat_completions(request_data: models.ChatCompletionRequest, http_request: Request):
    """
    Handles chat completion requests, processes potential commands, and proxies
    the request to the configured OpenRouter backend.

    It supports streaming and non-streaming responses. Special commands embedded
    in messages (e.g., `!/set(model=...)`) are processed by `proxy_logic`.
    """
    backend: OpenRouterBackend = http_request.app.state.openrouter_backend
    current_proxy_state: ProxyState = http_request.app.state.proxy_state # Access proxy_state from app.state

    logger.info(f"Received chat completion request for model: {request_data.model}")
    logger.debug(f"Incoming request payload: {request_data.model_dump_json(indent=2)}")

    processed_messages, commands_were_processed = process_commands_in_messages(
        request_data.messages,
        current_proxy_state # Pass the current_proxy_state instance
    )
    logger.debug(f"Processed messages: {processed_messages}, Commands processed: {commands_were_processed}")

    # Determine if the request is effectively command-only
    is_command_only_response = False
    if commands_were_processed:
        if not processed_messages:  # List is empty
            is_command_only_response = True
        else:
            # Check if all remaining messages are essentially empty strings (original content was just commands)
            all_remaining_messages_have_empty_content = True
            for msg in processed_messages:
                if isinstance(msg.content, str):
                    if msg.content.strip() != "":  # Found actual text
                        all_remaining_messages_have_empty_content = False
                        break
                elif isinstance(msg.content, list):  # If a list (multimodal) message remains, it's not purely command-only
                    # If process_commands_in_messages leaves a multimodal message, it implies it has non-command content (e.g., image, or unstripped text part)
                    all_remaining_messages_have_empty_content = False
                    break
                # No else needed as Pydantic validates ChatMessage.content
            if all_remaining_messages_have_empty_content:
                is_command_only_response = True

    if is_command_only_response:
        logger.info("Request contained only commands or resulted in effectively empty messages after command processing. Responding to client directly.")
        return models.CommandProcessedChatCompletionResponse(
            id="proxy_cmd_processed",
            object="chat.completion",
            created=int(datetime.utcnow().timestamp()),
            model=current_proxy_state.get_effective_model(request_data.model), # Use effective model
            choices=[
                models.ChatCompletionChoice(
                    index=0,
                    message=models.ChatCompletionChoiceMessage(role="assistant", content="Proxy command processed. No query sent to LLM."),
                    finish_reason="stop"
                )
            ],
            usage=models.CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        )

    # If not a command-only response, check if there's any valid content to send.
    # Valid content means processed_messages is not empty, AND at least one message has non-empty content.
    has_valid_content_to_send = False
    if processed_messages:  # If the list is not empty
        for msg in processed_messages:
            if isinstance(msg.content, str):
                if msg.content.strip() != "":
                    has_valid_content_to_send = True
                    break
            elif isinstance(msg.content, list):
                # For multimodal, if the list of content parts is not empty, it's considered valid content.
                # process_commands_in_messages removes messages if their content list becomes empty.
                # So, if a list-based message is present here, it has content (e.g., an image, or remaining text).
                if msg.content:  # Check if the list of parts is not empty
                    has_valid_content_to_send = True
                    break
    
    if not has_valid_content_to_send:
        logger.warning("Received request with no effective messages to send to the backend (either initially empty or became empty after processing, and not a command-only scenario).")
        raise HTTPException(status_code=400, detail="No messages provided in the request or messages became empty after processing.")

    # If we reach here, there's valid content to send to the backend.
    effective_model = current_proxy_state.get_effective_model(request_data.model)

    try:
        response = await backend.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            openrouter_api_base_url=OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=get_openrouter_headers,
        )
        if isinstance(response, StreamingResponse):
            return response
        logger.debug(f"Backend response JSON: {json.dumps(response, indent=2)}")
        return response

    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP error from backend: {e.response.status_code} - {e.response.text}",
            exc_info=True,
        )
        try:
            error_detail = e.response.json()
        except json.JSONDecodeError:
            error_detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        logger.error(
            f"Request error connecting to backend: {type(e).__name__} - {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Service unavailable: Could not connect to backend ({str(e)})",
        )
    except Exception as e:
        logger.error(f"An unexpected error occurred in chat_completions: {type(e).__name__} - {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/v1/models")
async def list_models(http_request: Request):
    """
    Proxies requests to the OpenRouter /models endpoint to list available models.
    """
    backend: OpenRouterBackend = http_request.app.state.openrouter_backend
    logger.info("Received request for /v1/models")

    try:
        models_data = await backend.list_models(
            openrouter_api_base_url=OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=get_openrouter_headers,
        )
        logger.debug(
            f"Successfully fetched models from backend. Count: {len(models_data.get('data', []))}"
        )

        # Optionally: annotate models_data here if needed.
        return models_data

    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP error from backend fetching models: {e.response.status_code} - {e.response.text}",
            exc_info=True,
        )
        try:
            error_detail = e.response.json()
        except json.JSONDecodeError:
            error_detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        logger.error(
            f"Request error connecting to backend for models: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Service unavailable: Could not connect to backend for models ({str(e)})",
        )
    except Exception as e:
        logger.error(f"An unexpected error occurred fetching models: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error fetching models: {str(e)}")

# --- Main execution for running with Uvicorn directly (optional) ---
if __name__ == "__main__":
    import uvicorn

    if not OPENROUTER_API_KEY:
        print("CRITICAL: OPENROUTER_API_KEY environment variable is not set.")
        print("Please set it in a .env file or in your environment.")

    logger.info(f"Starting Uvicorn server on {PROXY_HOST}:{PROXY_PORT}")
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)
