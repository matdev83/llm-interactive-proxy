import logging
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime # Needed for command-only response timestamp

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from models import ChatCompletionRequest
from proxy_logic import proxy_state, process_commands_in_messages
from src.connectors import OpenRouterBackend # Import the backend

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
    # Startup: Initialize the HTTP client and the backend connector
    logger.info("Application startup: Initializing HTTPX client and OpenRouterBackend.")
    app.state.httpx_client = httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT)
    app.state.openrouter_backend = OpenRouterBackend() # Instantiate the backend
    if not OPENROUTER_API_KEY: # Log this warning again after client/backend setup attempt
        logger.warning("OPENROUTER_API_KEY is not configured. Requests to OpenRouter will likely fail.")
    yield
    # Shutdown: Close the HTTP client
    logger.info("Application shutdown: Closing HTTPX client.")
    await app.state.httpx_client.aclose()

app = FastAPI(lifespan=lifespan)

# --- Helper Functions ---
def get_openrouter_headers() -> dict:
    """
    Generates the required HTTP headers for authenticating with the OpenRouter API.

    Raises:
        HTTPException: If the OPENROUTER_API_KEY is not set, indicating a server misconfiguration.

    Returns:
        A dictionary containing the necessary headers.
    """
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="Proxy server misconfiguration: OpenRouter API key not set.")
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": APP_SITE_URL,
        "X-Title": APP_X_TITLE,
        "User-Agent": f"{APP_X_TITLE}/1.0 (Python httpx)",
    }

# --- API Endpoints ---
@app.get("/")
async def root():
    """Provides a simple welcome message indicating the server is running."""
    logger.info("Root endpoint '/' accessed.")
    return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

@app.post("/v1/chat/completions")
async def chat_completions(request_data: ChatCompletionRequest, http_request: Request):
    """
    Handles chat completion requests, processes potential commands, and proxies
    the request to the configured OpenRouter backend.

    It supports streaming and non-streaming responses. Special commands embedded
    in messages (e.g., `!/set(model=...)`) are processed by `proxy_logic`.
    """
    client: httpx.AsyncClient = http_request.app.state.httpx_client
    backend: OpenRouterBackend = http_request.app.state.openrouter_backend

    logger.info(f"Received chat completion request for model: {request_data.model}")
    logger.debug(f"Incoming request payload: {request_data.model_dump_json(indent=2)}")

    processed_messages, commands_were_processed = process_commands_in_messages(request_data.messages)

    if not processed_messages:
        if commands_were_processed:
            logger.info("Request contained only commands and messages list is now empty. Responding to client directly.")
            return {
                "id": "proxy_cmd_processed",
                "object": "chat.completion",
                "created": int(datetime.utcnow().timestamp()),
                "model": proxy_state.override_model or request_data.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "Proxy command processed. No query sent to LLM."},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }
        else:
            logger.warning("Received request with no messages after processing (and no commands found).")
            raise HTTPException(status_code=400, detail="No messages provided in the request.")

    effective_model = proxy_state.get_effective_model(request_data.model)

    try:
        # Delegate to the backend connector
        return await backend.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            client=client,
            openrouter_api_base_url=OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=get_openrouter_headers
        )
    except HTTPException:
        # Re-raise if the backend already processed it into an HTTPException
        raise
    except Exception as e:
        # Catch any other unexpected errors from the backend call
        logger.error(f"An unexpected error occurred calling the backend connector: {type(e).__name__} - {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error during backend communication: {str(e)}")

@app.get("/v1/models")
async def list_models(http_request: Request):
    """
    Proxies requests to the OpenRouter /models endpoint to list available models.
    """
    client: httpx.AsyncClient = http_request.app.state.httpx_client
    logger.info("Received request for /v1/models")

    headers = get_openrouter_headers() # Re-fetch headers here, as they might change or be dynamic

    try:
        response = await client.get(f"{OPENROUTER_API_BASE_URL}/models", headers=headers)
        logger.debug(f"OpenRouter /models response status: {response.status_code}")
        response.raise_for_status()

        models_data = response.json()
        logger.debug(f"Successfully fetched models from OpenRouter. Count: {len(models_data.get('data', []))}")

        return models_data

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from OpenRouter fetching models: {e.response.status_code} - {e.response.text}", exc_info=True)
        try:
            error_detail = e.response.json()
        except json.JSONDecodeError:
            error_detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        logger.error(f"Request error connecting to OpenRouter for models: {str(e)}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to OpenRouter for models ({str(e)})")
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
