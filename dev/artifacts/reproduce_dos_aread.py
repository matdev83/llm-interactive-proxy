
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
from src.connectors.gemini import GeminiBackend
from src.core.common.exceptions import BackendError, ServiceUnavailableError

class MockHttpxResponse:
    def __init__(self, status_code, huge_body_size):
        self.status_code = status_code
        self.headers = {}
        self.huge_body_size = huge_body_size
        self.aclose = AsyncMock()

    async def aread(self):
        # Simulate reading a huge body
        print(f"Mock response: attempting to read {self.huge_body_size} bytes...")
        if self.huge_body_size > 100 * 1024 * 1024:
             raise MemoryError("OOM simulated")
        return b"a" * self.huge_body_size

class TestGeminiAreadDoS(unittest.IsolatedAsyncioTestCase):
    async def test_handle_gemini_streaming_response_oom(self):
        # Setup
        client = MagicMock()
        client.build_request.return_value = "request"
        
        # Simulate a 500 error with a massive body (e.g. 1GB)
        response = MockHttpxResponse(status_code=500, huge_body_size=200 * 1024 * 1024) # 200MB
        client.send = AsyncMock(return_value=response)
        
        backend = GeminiBackend(client=client, config=MagicMock(), translation_service=MagicMock())
        backend.gemini_api_base_url = "http://test"
        
        # Execute
        print("Testing _handle_gemini_streaming_response with huge error body...")
        try:
            await backend._handle_gemini_streaming_response(
                base_url="http://test",
                payload={},
                headers={},
                effective_model="gemini-pro"
            )
        except MemoryError:
            print("Caught expected MemoryError (DoS confirmed)")
            return
        except BackendError as e:
            print(f"Caught BackendError: {e}")
        except Exception as e:
            print(f"Caught unexpected exception: {e}")
            
    async def test_stream_completion_oom(self):
        # Setup
        client = MagicMock()
        client.build_request.return_value = "request"
        
        # Simulate a 500 error with a massive body
        response = MockHttpxResponse(status_code=500, huge_body_size=200 * 1024 * 1024) # 200MB
        client.send = AsyncMock(return_value=response)
        
        backend = GeminiBackend(client=client, config=MagicMock(), translation_service=MagicMock())
        
        # Create a dummy request object
        request = MagicMock()
        request.messages = []
        request.model = "gemini-pro"
        request.extra_body = {"gemini_api_base_url": "http://test", "api_key": "key", "key_name": "key"}
        
        backend.translation_service.from_domain_request.return_value = {}
        
        # Execute
        print("\nTesting stream_completion with huge error body...")
        try:
            gen = backend.stream_completion(request)
            await gen.__anext__()
        except MemoryError:
            print("Caught expected MemoryError (DoS confirmed)")
            return
        except BackendError as e:
            print(f"Caught BackendError: {e}")
        except Exception as e:
            print(f"Caught unexpected exception: {e}")

if __name__ == "__main__":
    unittest.main()
