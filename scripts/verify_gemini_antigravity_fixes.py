import asyncio
import json

# Add project root to python path
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.getcwd())

from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StopChunkWithUsage, UsageChunkLeakError
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.response_adapters import to_fastapi_streaming_response


async def main():
    print("Starting verification of Antigravity OAuth fixes...")

    # 1. Setup Dependencies
    config = AppConfig()
    translation_service = TranslationService()

    # Mock Client
    client = AsyncMock()

    # Instantiate Connector
    connector = AntigravityOAuthConnector(
        client=client, config=config, translation_service=translation_service
    )

    # Bypass auth checks for this test
    connector._oauth_credentials = {"access_token": "mock_token"}
    connector._refresh_token_if_needed = AsyncMock(return_value=True)
    connector._discover_project_id = AsyncMock(return_value="mock-project")
    connector._validate_runtime_credentials = AsyncMock(return_value=True)
    connector._ensure_healthy = AsyncMock()

    # Mock translation_service.to_domain_stream_chunk to return well-formed chunks
    # This decouples the test from actual translation logic to verify proxy pipeline
    def mock_to_domain_stream_chunk_impl(chunk, source_format):
        if source_format != "code_assist":
            # For this demo, assume only code_assist format
            return {}

        if chunk.get("candidates"):
            candidate = chunk["candidates"][0]
            if candidate.get("content"):
                parts = candidate["content"].get("parts", [])
                text_content = "".join([p["text"] for p in parts if p.get("text")])

                function_call = None
                for p in parts:
                    if p.get("functionCall"):
                        function_call = p["functionCall"]
                        break

                delta = {}
                if text_content:
                    delta["content"] = text_content
                if function_call:
                    delta["tool_calls"] = [
                        {
                            "id": "call_123",  # Mocked ID
                            "type": "function",
                            "function": function_call,
                        }
                    ]

                return {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "gemini-2.5-pro",
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": (
                                None
                                if not candidate.get("finishReason")
                                else candidate["finishReason"].lower()
                            ),
                        }
                    ],
                }
            elif (
                chunk.get("candidates")[0].get("finishReason") == "STOP"
            ):  # Check if the STOP is within candidates
                return {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "gemini-2.5-pro",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
        return {}  # Fallback for unexpected format

    translation_service.to_domain_stream_chunk = MagicMock(
        side_effect=mock_to_domain_stream_chunk_impl
    )

    # 2. Mock the Code Assist API Response

    # 2. Mock the Code Assist API Response
    mock_response_chunks = [
        # Chunk 1: Text Content (Regular body)
        b'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}, "finishReason": null}]}\n\n',
        # Chunk 2: More Text
        b'data: {"candidates": [{"content": {"parts": [{"text": ", world!"}]}, "finishReason": null}]}\n\n',
        # Chunk 3: Tool Call
        b'data: {"candidates": [{"content": {"parts": [{"functionCall": {"name": "search_web", "args": {"query": "weather"}}}]}, "finishReason": null}]}\n\n',
        # Chunk 4: Stop
        b'data: {"candidates": [{"finishReason": "STOP"}]}\n\n',
        # SSE Done
        b"data: [DONE]\n\n",
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200

    def iter_content_sync(chunk_size=None, decode_unicode=False):
        yield from mock_response_chunks

    mock_response.iter_content = iter_content_sync

    # Mock the AuthorizedSession
    mock_auth_session = MagicMock()
    mock_auth_session.request.return_value = mock_response

    # 3. Execute the Flow
    print("\nExecuting mock chat completion...")

    request_data = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    with patch(
        "google.auth.transport.requests.AuthorizedSession",
        return_value=mock_auth_session,
    ):
        # Get the domain envelope
        envelope = await connector.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model="gemini-2.5-pro",
        )

        # Pass through the FastAPI adapter (this was the source of the usage leak)
        fastapi_response = to_fastapi_streaming_response(envelope)

        # 4. Verify Output
        print("\nVerifying Output Stream:")

        full_content = ""
        received_tool_calls = []
        usage_received = None
        finish_reason_received = None
        chunk_count = 0

        async for bytes_chunk in fastapi_response.body_iterator:
            chunk_str = (
                bytes_chunk.decode("utf-8")
                if isinstance(bytes_chunk, bytes)
                else str(bytes_chunk)
            )
            # Parse SSE
            lines = chunk_str.strip().split("\n")
            for line in lines:
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        print("Received [DONE]")
                        continue

                    try:
                        data = json.loads(data_str)
                        chunk_count += 1

                        # Debug: Print raw data to understand what's coming through
                        # print(f"DEBUG: Received chunk: {json.dumps(data)}")

                        # Check for content
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})

                            # VERIFY: No leaked usage in content
                            content = delta.get("content")
                            if content:
                                # Heuristic check for leaked JSON
                                if (
                                    isinstance(content, str)
                                    and content.strip().startswith("{")
                                    and "usage" in content
                                ):
                                    print(
                                        f"FAIL: Detected leaked JSON structure in content: {content}"
                                    )
                                    return
                                full_content += content
                                print(f"Received content chunk: {content}")

                            # VERIFY: Tool calls
                            tool_calls = delta.get("tool_calls")
                            if tool_calls:
                                received_tool_calls.extend(tool_calls)
                                print(f"Received tool calls: {tool_calls}")

                            # VERIFY: Finish reason
                            fr = data["choices"][0].get("finish_reason")
                            if fr:
                                finish_reason_received = fr
                                print(f"Received finish_reason: {fr}")

                        # VERIFY: Usage in standard format
                        if "usage" in data:
                            usage_received = data["usage"]
                            print(f"Received usage info: {usage_received}")

                    except json.JSONDecodeError:
                        print(f"Failed to parse JSON: {data_str}")

    # Debug: Test translation logic directly if content was missing
    if not full_content:
        print("\nDEBUG: Testing translation service directly...")
        test_chunk = {
            "candidates": [
                {"content": {"parts": [{"text": "Hello"}]}, "finishReason": None}
            ]
        }
        domain = translation_service.to_domain_stream_chunk(test_chunk, "code_assist")
        print(f"Direct translation result: {domain}")

    # 5. Final Verification
    print("\n--- Final Verification ---")

    # Point 1: Regular message bodies
    if full_content == "Hello, world!":
        print("✅ PASS: Regular message bodies received correctly.")
    else:
        print(
            f"❌ FAIL: Message content mismatch. Expected 'Hello, world!', got '{full_content}'"
        )

    # Point 3: Tool call definitions
    if (
        len(received_tool_calls) > 0
        and received_tool_calls[0]["function"]["name"] == "search_web"
    ):
        print("PASS: Tool calls received correctly.")
    else:
        print("FAIL: Tool calls not received or incorrect.")

    # Point 4: No leaked data structures
    # We checked this in the loop, if we reached here with clean content
    if "{" not in full_content:  # Simple check that we didn't get JSON text
        print("✅ PASS: No leaked data structures detected in content.")
    else:
        print("⚠️ WARNING: Content contains '{', check if it's legitimate text or leak.")

    # Point 5: Proper usage information
    if usage_received and usage_received.get("total_tokens") is not None:
        print("✅ PASS: Usage information received in standard format.")
        print(f"   Token count: {usage_received}")
    else:
        print("❌ FAIL: Usage information MISSING or malformed.")

    # Point from bug 2: Finish reason
    if finish_reason_received == "stop":
        print("PASS: Proper finish_reason 'stop' received.")
    elif finish_reason_received == "tool_calls":
        # This might be acceptable if the tool call chunk was the last one before usage
        # But in our mock, we sent explicit STOP after tool calls.
        print(f"INFO: Finish reason was '{finish_reason_received}'")
    else:
        print(f"FAIL: Unexpected finish_reason: {finish_reason_received}")

    # --- Additional Tests for StopChunkWithUsage Protection ---
    print("\n--- StopChunkWithUsage Protection Tests ---")

    # Test 1: StopChunkWithUsage raises error when str() is called
    test_chunk = StopChunkWithUsage(
        {
            "id": "chatcmpl-test",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )

    try:
        str(test_chunk)
        print(
            "FAIL: StopChunkWithUsage did NOT raise error on str() - protection bypassed!"
        )
    except UsageChunkLeakError:
        print("PASS: StopChunkWithUsage correctly raises UsageChunkLeakError on str()")
    except Exception as e:
        print(
            f"FAIL: StopChunkWithUsage raised unexpected error: {type(e).__name__}: {e}"
        )

    # Test 2: StopChunkWithUsage survives ProcessedResponse without being converted
    proc_resp = ProcessedResponse(content=test_chunk, usage={"total_tokens": 15})
    if isinstance(proc_resp.content, StopChunkWithUsage):
        print("PASS: StopChunkWithUsage preserved through ProcessedResponse")
    else:
        print(
            f"FAIL: StopChunkWithUsage was converted to {type(proc_resp.content).__name__}"
        )

    # Test 3: Verify dict() conversion still works (for safe serialization)
    try:
        converted = dict(test_chunk)
        if "usage" in converted and converted["usage"]["total_tokens"] == 15:
            print("PASS: StopChunkWithUsage can be safely converted with dict()")
        else:
            print("FAIL: dict() conversion lost data")
    except Exception as e:
        print(f"FAIL: dict() conversion raised error: {e}")

    print("\n--- All Verification Complete ---")


if __name__ == "__main__":
    asyncio.run(main())
