import logging
import os
import json
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from backends import OpenRouterBackend

from models import ChatCompletionRequest
from proxy_logic import proxy_state, process_commands_in_messages

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
    level=logging.DEBUG, # Set to INFO for less verbosity in production
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

if not OPENROUTER_API_KEY:
    logger.critical("OPENROUTER_API_KEY is not set. The proxy will not be able to connect to OpenRouter.")
    # Potentially exit or raise a configuration error here if you want to prevent startup

# --- HTTP Client Lifecycle ---
# Using a global httpx.AsyncClient instance is recommended for performance.
# It should be managed with FastAPI's lifespan events.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize the HTTP client
    logger.info("Application startup: Initializing HTTPX client.")
    client = httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT)
    app.state.httpx_client = client
    app.state.backend = OpenRouterBackend(
        client,
        api_key=OPENROUTER_API_KEY or "",
        api_base_url=OPENROUTER_API_BASE_URL,
        app_site_url=APP_SITE_URL,
        app_title=APP_X_TITLE,
    )
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
    logger.info("Root endpoint '/' accessed.")
    return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

@app.post("/v1/chat/completions")
async def chat_completions(request_data: ChatCompletionRequest, http_request: Request):
    
    logger.info(f"Received chat completion request for model: {request_data.model}")
    logger.debug(f"Incoming request payload: {request_data.model_dump_json(indent=2)}")

    processed_messages, commands_were_processed = process_commands_in_messages(request_data.messages)

    if not processed_messages:
        if commands_were_processed:
            logger.info("Request contained only commands and messages list is now empty. Responding to client directly.")
            # This indicates the user's input consisted solely of commands that resulted in no actual content to send.
            return {
                "id": "proxy_cmd_processed", 
                "object": "text_completion", # Or chat.completion for consistency
                "created": int(json.loads(json.dumps(datetime.utcnow(), default=str))[:-3] + "Z"), # Simulate timestamp
                "model": proxy_state.override_model or request_data.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "Proxy command processed. No query sent to LLM."},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            } # Mimic an OpenAI-like response for command-only interactions.
        else:
            # No commands processed and messages are empty - this is an invalid request.
            logger.warning("Received request with no messages after processing (and no commands found).")
            raise HTTPException(status_code=400, detail="No messages provided in the request.")


    effective_model = proxy_state.get_effective_model(request_data.model)

    backend_request = request_data.copy(deep=True)
    backend_request.model = effective_model
    backend_request.messages = processed_messages

    backend = http_request.app.state.backend

    logger.info(
        f"Forwarding to backend. Effective model: {effective_model}. Stream: {backend_request.stream}"
    )

    try:
        if backend_request.stream:
            logger.debug("Initiating stream request to backend.")
            stream_iter = await backend.chat_completion(backend_request, stream=True)
            return StreamingResponse(stream_iter, media_type="text/event-stream")

        logger.debug("Initiating non-streaming request to backend.")
        response_json = await backend.chat_completion(backend_request)
        logger.debug(f"Backend response JSON: {json.dumps(response_json, indent=2)}")
        return response_json

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
    backend: OpenRouterBackend = http_request.app.state.backend
    logger.info("Received request for /v1/models")

    try:
        models_data = await backend.list_models()
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
    from datetime import datetime # For the command-only response timestamp
    
    if not OPENROUTER_API_KEY:
        print("CRITICAL: OPENROUTER_API_KEY environment variable is not set.")
        print("Please set it in a .env file or in your environment.")
        # exit(1) # Or allow it to run but log warnings. FastAPI app.state.httpx_client will be problematic.

    logger.info(f"Starting Uvicorn server on {PROXY_HOST}:{PROXY_PORT}")
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)
