"""Generate a small test CBOR capture file matching the V2 wire format."""

import json
import time
from pathlib import Path

import cbor2

MAGIC = "LLMPROXY-CAPTURE-V2"
VERSION = 2

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "var" / "wire_captures_cbor"
OUTPUT_FILE = OUTPUT_DIR / "test_capture.cbor"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    session_id = "sess-test-001"
    t0 = time.time()

    # Header
    header = {
        "magic": MAGIC,
        "version": VERSION,
        "created_at": t0,
        "session_id": session_id,
        "metadata": {},
    }

    # ---- SSE data blobs (UTF-8 bytes) ----
    request_json = json.dumps(
        {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
    )

    sse_lines = (
        'data: {"id":"chatcmpl-9x00","object":"chat.completion.chunk",'
        '"created":1713200000,"model":"gpt-4o-2024-05-13",'
        '"choices":[{"index":0,"delta":{"role":"assistant","content":""},"logprobs":null,"finish_reason":null}]}\n\n'
        'data: {"id":"chatcmpl-9x00","object":"chat.completion.chunk",'
        '"created":1713200000,"model":"gpt-4o-2024-05-13",'
        '"choices":[{"index":0,"delta":{"content":"Hello"},"logprobs":null,"finish_reason":null}]}\n\n'
        'data: {"id":"chatcmpl-9x00","object":"chat.completion.chunk",'
        '"created":1713200000,"model":"gpt-4o-2024-05-13",'
        '"choices":[{"index":0,"delta":{"content":"!"},"logprobs":null,"finish_reason":null}]}\n\n'
        "data: [DONE]\n\n"
    )

    response_json = json.dumps(
        {
            "id": "chatcmpl-9x00",
            "object": "chat.completion",
            "created": 1713200000,
            "model": "gpt-4o-2024-05-13",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 2,
                "total_tokens": 7,
            },
        }
    )

    entries = [
        # 1. CLIENT_TO_PROXY — inbound request
        {
            "ts": t0,
            "dir": 0,
            "seq": 1,
            "data": request_json.encode(),
            "meta": {
                "sid": session_id,
                "be": "openai",
                "mod": "gpt-4o",
                "rid": "req-001",
            },
        },
        # 2. PROXY_TO_BACKEND — outbound request
        {
            "ts": t0 + 0.005,
            "dir": 2,
            "seq": 2,
            "data": request_json.encode(),
            "meta": {
                "sid": session_id,
                "be": "openai",
                "mod": "gpt-4o",
                "rid": "req-001",
            },
        },
        # 3. BACKEND_TO_PROXY — stream start (empty, ss=True)
        {
            "ts": t0 + 0.120,
            "dir": 3,
            "seq": 3,
            "data": b"",
            "meta": {
                "sid": session_id,
                "be": "openai",
                "rid": "req-001",
                "sc": 200,
                "ss": True,
            },
        },
        # 4. BACKEND_TO_PROXY — SSE data chunk
        {
            "ts": t0 + 0.125,
            "dir": 3,
            "seq": 4,
            "data": sse_lines.encode(),
            "meta": {
                "sid": session_id,
                "be": "openai",
                "rid": "req-001",
                "ci": 0,
            },
        },
        # 5. BACKEND_TO_PROXY — stream end (empty, se=True)
        {
            "ts": t0 + 0.130,
            "dir": 3,
            "seq": 5,
            "data": b"",
            "meta": {
                "sid": session_id,
                "be": "openai",
                "rid": "req-001",
                "se": True,
                "tc": 1,
                "tb": len(sse_lines),
            },
        },
        # 6. PROXY_TO_CLIENT — assembled response to client
        {
            "ts": t0 + 0.135,
            "dir": 1,
            "seq": 6,
            "data": response_json.encode(),
            "meta": {
                "sid": session_id,
                "be": "openai",
                "mod": "gpt-4o",
                "rid": "req-001",
            },
        },
    ]

    with open(OUTPUT_FILE, "wb") as f:
        cbor2.dump(header, f)
        for entry in entries:
            cbor2.dump(entry, f)

    size = OUTPUT_FILE.stat().st_size
    print(f"Wrote {len(entries)} entries to {OUTPUT_FILE} ({size} bytes)")


if __name__ == "__main__":
    main()
