import asyncio
import sys
import os
sys.path.append(os.getcwd())
import unittest.mock
from unittest.mock import AsyncMock, MagicMock

# Create the large payload
LARGE_PAYLOAD_SIZE = 15 * 1024 * 1024
large_payload = b'{"data": "' + (b"x" * LARGE_PAYLOAD_SIZE) + b'"}'

async def run_repro():
    # Patch json.loads in the module
    with unittest.mock.patch("src.core.app.middleware.sso_middleware_adapter.json.loads") as mock_json_loads:
        from src.core.app.middleware.sso_middleware_adapter import SSOMiddlewareAdapter
        
        # Mock dependencies
        mock_sso_middleware = AsyncMock()
        mock_sso_middleware.sandbox_handler = MagicMock()
        mock_sso_middleware.sandbox_handler.generate_login_banner = AsyncMock(return_value={})
        
        mock_request = MagicMock()
        mock_request.url.path = "/v1/chat/completions"
        mock_request.method = "POST"
        mock_request.headers = {"authorization": "Bearer test-token"}
        mock_request.body = AsyncMock(return_value=large_payload)
        # Mock _receive needed for cache mechanism
        mock_request._receive = None
        
        app = MagicMock()
        adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        
        print(f"Sending payload of size: {len(large_payload)} bytes")
        try:
            await adapter.dispatch(mock_request, call_next)
        except Exception as e:
            print(f"Exception during dispatch: {e}")

        if mock_json_loads.called:
            args, _ = mock_json_loads.call_args
            arg_len = len(args[0])
            print(f"json.loads called with argument of length: {arg_len}")
            if arg_len >= LARGE_PAYLOAD_SIZE:
                print("VULNERABILITY CONFIRMED: json.loads called with large payload")
            else:
                print(f"json.loads called with smaller payload: {arg_len}")
        else:
            print("json.loads NOT called")

if __name__ == "__main__":
    asyncio.run(run_repro())
