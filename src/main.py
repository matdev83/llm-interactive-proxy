import logging
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

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
    app.state.httpx_client = httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT)
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not configured. Requests to OpenRouter will likely fail.")
    yield
    # Shutdown: Close the HTTP client
    logger.info("Application shutdown: Closing HTTPX client.")
    await app.state.httpx_client.aclose()

app = FastAPI(lifespan=lifespan)

# --- Helper Functions ---
def get_openrouter_headers() -> dict:
    if not OPENROUTER_API_KEY:
        # This case should ideally be handled by not starting or raising prominently.
        # If we reach here, it's a misconfiguration.
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
    logger.info("Root endpoint '/' accessed.")
    return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

@app.post("/v1/chat/completions")
async def chat_completions(request_data: ChatCompletionRequest, http_request: Request): # http_request gives access to FastAPI app state
    client: httpx.AsyncClient = http_request.app.state.httpx_client
    
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
                "created": int(datetime.utcnow().timestamp()),
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
    
    openrouter_payload = request_data.model_dump(exclude_unset=True)
    openrouter_payload["model"] = effective_model
    # Convert Pydantic message models back to dictionaries for the payload
    openrouter_payload["messages"] = [msg.model_dump(exclude_unset=True) for msg in processed_messages]

    logger.info(f"Forwarding to OpenRouter. Effective model: {effective_model}. Stream: {request_data.stream}")
    logger.debug(f"Payload for OpenRouter: {json.dumps(openrouter_payload, indent=2)}")

    headers = get_openrouter_headers()

    try:
        if request_data.stream:
            logger.debug("Initiating stream request to OpenRouter.")
            req = client.build_request("POST", f"{OPENROUTER_API_BASE_URL}/chat/completions",
                                       json=openrouter_payload, headers=headers)
            
            async def stream_generator():
                try:
                    async with client.stream(req) as response:
                        logger.debug(f"OpenRouter stream response status: {response.status_code}")
                        response.raise_for_status() # Check for HTTP errors from OpenRouter
                        async for chunk in response.aiter_bytes():
                            # logger.debug(f"Stream chunk (bytes): {chunk[:100]}") # Log first 100 bytes
                            yield chunk
                        logger.debug("OpenRouter stream finished.")
                except httpx.HTTPStatusError as e_stream:
                    logger.error(f"HTTP error during OpenRouter stream: {e_stream.response.status_code} - {await e_stream.response.aread()}")
                    # This error won't be caught by the outer try/except if it happens inside the generator
                    # It's complex to propagate this back as an HTTPException directly from here.
                    # The client will see a broken stream.
                    # For robust error reporting in streams, one might stream an error message in SSE format.
                    yield f"data: {json.dumps({'error': {'message': f'OpenRouter stream error: {e_stream.response.status_code}', 'type': 'openrouter_error', 'code': e_stream.response.status_code}})}\n\n".encode()
                except Exception as e_gen:
                    logger.error(f"Error in stream generator: {e_gen}", exc_info=True)
                    yield f"data: {json.dumps({'error': {'message': f'Proxy stream generator error: {str(e_gen)}', 'type': 'proxy_error'}})}\n\n".encode()


            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        else: # Non-streaming request
            logger.debug("Initiating non-streaming request to OpenRouter.")
            response = await client.post(f"{OPENROUTER_API_BASE_URL}/chat/completions",
                                         json=openrouter_payload, headers=headers)
            logger.debug(f"OpenRouter non-stream response status: {response.status_code}")
            response.raise_for_status() # Raise HTTP errors
            
            response_json = response.json()
            logger.debug(f"OpenRouter response JSON: {json.dumps(response_json, indent=2)}")
            return response_json

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from OpenRouter: {e.response.status_code} - {e.response.text}", exc_info=True)
        try:
            error_detail = e.response.json()
        except json.JSONDecodeError:
            error_detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        logger.error(f"Request error connecting to OpenRouter: {type(e).__name__} - {str(e)}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to OpenRouter ({str(e)})")
    except Exception as e:
        logger.error(f"An unexpected error occurred in chat_completions: {type(e).__name__} - {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/v1/models")
async def list_models(http_request: Request):
    client: httpx.AsyncClient = http_request.app.state.httpx_client
    logger.info("Received request for /v1/models")
    
    headers = get_openrouter_headers()
    
    try:
        response = await client.get(f"{OPENROUTER_API_BASE_URL}/models", headers=headers)
        logger.debug(f"OpenRouter /models response status: {response.status_code}")
        response.raise_for_status()
        
        models_data = response.json()
        logger.debug(f"Successfully fetched models from OpenRouter. Count: {len(models_data.get('data', []))}")
        
        # Optionally: Modify models_data here if needed.
        # For example, to add info about the currently overridden model.
        # if proxy_state.override_model:
        #     models_data["proxy_override_active"] = proxy_state.override_model
        
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
    from datetime import datetime # For the command-only response timestamp
    
    if not OPENROUTER_API_KEY:
        print("CRITICAL: OPENROUTER_API_KEY environment variable is not set.")
        print("Please set it in a .env file or in your environment.")
        # exit(1) # Or allow it to run but log warnings. FastAPI app.state.httpx_client will be problematic.

    logger.info(f"Starting Uvicorn server on {PROXY_HOST}:{PROXY_PORT}")
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)