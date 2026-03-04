"""
Minimal streaming test client for qwen-oauth backend.

Tests that:
1. Streaming works end-to-end through the proxy
2. Model name normalization works (qwen-oauth:qwen/coder-model → coder-model)
3. Content is visible (reasoning_content coerced to content)
4. Stream doesn't end after first token
"""

import asyncio
import sys
import time

import httpx


PROXY_URL = "http://127.0.0.1:8002/v1/chat/completions"
MODEL = "qwen-oauth:qwen/coder-model"


async def test_streaming() -> None:
    """Test streaming chat completion through the proxy."""
    print(f"{'='*60}")
    print(f"Qwen OAuth Streaming Test")
    print(f"Proxy: {PROXY_URL}")
    print(f"Model: {MODEL}")
    print(f"{'='*60}\n")

    payload: dict = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "Write a Python function that checks if a number is prime. Be concise."}
        ],
        "stream": True,
        "max_tokens": 200,
    }

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }

    print("[1] Sending streaming request...")
    start_time: float = time.monotonic()
    total_chunks: int = 0
    content_chunks: int = 0
    accumulated_text: str = ""
    first_token_time: float | None = None
    finish_reason: str | None = None
    saw_done: bool = False

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", PROXY_URL, json=payload, headers=headers) as response:
                print(f"[2] Response status: {response.status_code}")
                print(f"[2] Content-Type: {response.headers.get('content-type', 'unknown')}")

                if response.status_code != 200:
                    body: bytes = await response.aread()
                    print(f"[ERROR] Response body: {body.decode('utf-8', errors='replace')}")
                    return

                print(f"\n[3] Streaming chunks:\n{'─'*40}")

                async for line_bytes in response.aiter_lines():
                    line: str = line_bytes.strip()
                    if not line:
                        continue

                    total_chunks += 1

                    if line == "data: [DONE]":
                        saw_done = True
                        print(f"\n{'─'*40}")
                        print(f"[DONE] marker received")
                        continue

                    if line.startswith("data: "):
                        data_str: str = line[6:]
                        try:
                            import json
                            data: dict = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                choice: dict = choices[0]
                                delta: dict = choice.get("delta", {})
                                content: str | None = delta.get("content")
                                reasoning: str | None = delta.get("reasoning_content")
                                fr: str | None = choice.get("finish_reason")

                                if fr:
                                    finish_reason = fr

                                if content:
                                    if first_token_time is None:
                                        first_token_time = time.monotonic()
                                    content_chunks += 1
                                    accumulated_text += content
                                    # Print content inline
                                    sys.stdout.write(content)
                                    sys.stdout.flush()

                                if reasoning:
                                    # This should NOT appear after our fix
                                    # (it should be coerced into content)
                                    print(f"\n[WARN] Got separate reasoning_content: {reasoning[:50]}...")

                        except json.JSONDecodeError:
                            print(f"  [parse error] {data_str[:100]}")

        except httpx.ReadTimeout:
            print(f"\n[ERROR] Read timeout after {time.monotonic() - start_time:.1f}s")
        except httpx.ConnectError as e:
            print(f"\n[ERROR] Connection failed: {e}")
            print("Is the proxy server running on port 8002?")
            return

    elapsed: float = time.monotonic() - start_time
    ttft: float | None = (first_token_time - start_time) if first_token_time else None

    print(f"\n\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"  Total SSE chunks:     {total_chunks}")
    print(f"  Content chunks:       {content_chunks}")
    print(f"  Accumulated length:   {len(accumulated_text)} chars")
    print(f"  Finish reason:        {finish_reason}")
    print(f"  [DONE] received:      {saw_done}")
    print(f"  Time to first token:  {ttft:.2f}s" if ttft else "  Time to first token:  N/A")
    print(f"  Total elapsed:        {elapsed:.2f}s")
    print(f"{'='*60}")

    # Verdict
    print(f"\nVERDICT:")
    ok: bool = True
    if content_chunks == 0:
        print(f"  ❌ FAIL: No content chunks received (stream was empty)")
        ok = False
    elif content_chunks <= 1:
        print(f"  ❌ FAIL: Only {content_chunks} content chunk(s) — stream ended prematurely")
        ok = False
    else:
        print(f"  ✓ Content chunks: {content_chunks} (multiple tokens received)")

    if len(accumulated_text) < 10:
        print(f"  ❌ FAIL: Accumulated text too short ({len(accumulated_text)} chars)")
        ok = False
    else:
        print(f"  ✓ Accumulated text: {len(accumulated_text)} chars")

    if not saw_done:
        print(f"  ⚠ WARNING: No [DONE] marker — stream may have been cut short")

    if finish_reason == "stop":
        print(f"  ✓ Finish reason: stop (clean completion)")
    elif finish_reason:
        print(f"  ⚠ Finish reason: {finish_reason}")
    else:
        print(f"  ⚠ WARNING: No finish_reason received")

    if ok:
        print(f"\n  ✅ STREAMING FIX VERIFIED — Multiple tokens received successfully!")
    else:
        print(f"\n  ❌ STREAMING STILL BROKEN — See details above")


if __name__ == "__main__":
    asyncio.run(test_streaming())
