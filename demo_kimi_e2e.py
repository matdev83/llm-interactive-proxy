import asyncio
import contextlib
import inspect
import json
import os
import sys

# Add current directory to sys.path to ensure src is importable
sys.path.append(os.getcwd())

# Import required components from the project
from src.core.di.services import get_service_collection, register_core_services
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.services.backend_service import BackendService


async def run_demo():
    print("=== Kimi Code Backend End-to-End Demo ===")

    # 1. Setup environment and configuration
    if not os.getenv("KIMI_API_KEY"):
        print("Error: KIMI_API_KEY environment variable is not set.")
        return

    # 2. Initialize Service Provider and BackendService
    services = get_service_collection()
    register_core_services(services)
    provider = services.build_service_provider()

    backend_service = provider.get_required_service(BackendService)

    # 3. Prepare the ChatRequest
    model_string = "kimi-code:kimi/kimi-for-coding"

    messages = [
        ChatMessage(
            role="system",
            content=(
                "Output only the final answer. "
                "Do not include meta commentary about the prompt, requirements, or your planning."
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                "Explain how to implement an in-memory rate limiter in Python for an HTTP API. "
                "Write 6-10 sentences across multiple paragraphs, then provide a short code example "
                "(around 30-60 lines) using only the standard library."
            ),
        ),
    ]

    request = ChatRequest(
        # Use a higher token budget to ensure we can observe a longer multi-sentence response.
        model=model_string,
        messages=messages,
        max_tokens=1800,
        stream=True,
    )

    print(f"Sending prompt to model: {model_string}")
    print(f"Prompt: {messages[0].content}")
    print("-" * 40)

    # 4. Execute the request
    try:
        response_envelope = await backend_service.chat_completions(request)

        if isinstance(response_envelope, StreamingResponseEnvelope):
            print("Response received! Monitoring stream...")

            stream_iter = response_envelope.content
            if stream_iter is None:
                print("(no stream iterator returned)")
                return

            done_received = False
            full_text = ""
            content_text = ""
            reasoning_text = ""

            def _extract_text_from_openai_event(event: dict) -> tuple[str, str]:
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices:
                    return "", ""
                first = choices[0]
                if not isinstance(first, dict):
                    return "", ""
                delta = first.get("delta")
                if not isinstance(delta, dict):
                    return "", ""

                piece_content = delta.get("content")
                content_piece = piece_content if isinstance(piece_content, str) else ""

                piece_reasoning = delta.get("reasoning_content")
                reasoning_piece = (
                    piece_reasoning if isinstance(piece_reasoning, str) else ""
                )

                return content_piece, reasoning_piece

            def _process_sse_text(sse_text: str) -> tuple[str, str, bool]:
                emitted_content = ""
                emitted_reasoning = ""
                done = False

                # Split by SSE event boundary.
                for raw_event in sse_text.replace("\r\n", "\n").split("\n\n"):
                    if not raw_event.strip():
                        continue
                    for line in raw_event.split("\n"):
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            done = True
                            continue
                        try:
                            payload = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(payload, dict):
                            content_piece, reasoning_piece = (
                                _extract_text_from_openai_event(payload)
                            )
                            if content_piece:
                                emitted_content += content_piece
                            if reasoning_piece:
                                emitted_reasoning += reasoning_piece

                return emitted_content, emitted_reasoning, done

            try:
                async for chunk in stream_iter:
                    content = chunk.content
                    if content is None:
                        continue

                    if isinstance(content, bytes):
                        text = content.decode("utf-8", errors="replace")
                        piece_content, piece_reasoning, got_done = _process_sse_text(
                            text
                        )
                        piece = piece_content or piece_reasoning
                        if piece:
                            print(piece, end="", flush=True)
                            full_text += piece
                        if piece_content:
                            content_text += piece_content
                        if piece_reasoning:
                            reasoning_text += piece_reasoning
                        if got_done:
                            done_received = True
                        continue

                    if isinstance(content, str):
                        piece_content, piece_reasoning, got_done = _process_sse_text(
                            content
                        )
                        piece = piece_content or piece_reasoning
                        if piece:
                            print(piece, end="", flush=True)
                            full_text += piece
                        if piece_content:
                            content_text += piece_content
                        if piece_reasoning:
                            reasoning_text += piece_reasoning
                        if got_done:
                            done_received = True
                        continue

                    # Best-effort: already-decoded JSON dict event.
                    content_piece, reasoning_piece = _extract_text_from_openai_event(
                        content
                    )

                    if content_piece:
                        print(content_piece, end="", flush=True)
                        full_text += content_piece
                        content_text += content_piece
                    elif reasoning_piece:
                        print(reasoning_piece, end="", flush=True)
                        full_text += reasoning_piece
                        reasoning_text += reasoning_piece
            finally:
                # Ensure upstream stream is closed cleanly.
                if response_envelope.cancel_callback is not None:
                    with contextlib.suppress(Exception):
                        await response_envelope.cancel_callback()
                aclose = getattr(stream_iter, "aclose", None)
                if callable(aclose):
                    with contextlib.suppress(Exception):
                        maybe_awaitable = aclose()
                        if inspect.isawaitable(maybe_awaitable):
                            await maybe_awaitable
            print("\n" + "-" * 40)
            print("Stream finished.")
            print(f"[DONE] received: {done_received}")
            print(f"Output chars (printed): {len(full_text)}")
            print(f"Output chars (delta.content): {len(content_text)}")
            print(f"Output chars (delta.reasoning_content): {len(reasoning_text)}")
        else:
            print("Received non-streaming response:")
            print(json.dumps(response_envelope.content, indent=2))

    except Exception as e:
        print(f"\nError: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(run_demo())
