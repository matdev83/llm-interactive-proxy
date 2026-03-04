import json
import time
from pathlib import Path

import httpx


def _load_access_token() -> str:
    creds_path = Path.home() / ".qwen" / "oauth_creds.json"
    data = json.loads(creds_path.read_text(encoding="utf-8"))
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Missing access_token in oauth_creds.json")
    return token


def _build_headers(token: str) -> dict[str, str]:
    # Mimic qwen-code's DashScope headers (safe to send to portal as well).
    ua = "QwenCode/1.0.0 (win32; x64)"
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": ua,
        "X-DashScope-CacheControl": "enable",
        "X-DashScope-UserAgent": ua,
        "X-DashScope-AuthType": "qwen-oauth",
    }


def probe_non_stream() -> None:
    token = _load_access_token()
    url = "https://portal.qwen.ai/v1/chat/completions"
    payload = {
        "model": "coder-model",
        "messages": [
            {
                "role": "user",
                "content": "Hi there. What this project is all about?",
            }
        ],
        "stream": False,
        "max_tokens": 200,
    }

    with httpx.Client(http2=True, timeout=60) as client:
        r = client.post(url, headers=_build_headers(token), json=payload)
        print("non_stream status", r.status_code)
        text = r.text
        print("non_stream body_prefix", text[:300].replace("\n", "\\n"))


def probe_stream() -> None:
    token = _load_access_token()
    url = "https://portal.qwen.ai/v1/chat/completions"
    payload = {
        "model": "coder-model",
        "messages": [
            {
                "role": "user",
                "content": "Hi there. What this project is all about?",
            }
        ],
        "stream": True,
        "max_tokens": 200,
    }

    headers = _build_headers(token)
    headers["Accept"] = "text/event-stream"

    with httpx.Client(http2=True, timeout=60) as client:
        with client.stream("POST", url, headers=headers, json=payload) as r:
            print("stream status", r.status_code)
            start = time.time()
            printed = 0
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    print("sse", data[:240])
                    printed += 1
                    if data == "[DONE]" or printed >= 12:
                        break
                if time.time() - start > 20:
                    break


def main() -> int:
    probe_non_stream()
    probe_stream()
    # Try disabling thinking explicitly (some qwen3* models only emit reasoning_content otherwise).
    token = _load_access_token()
    url = "https://portal.qwen.ai/v1/chat/completions"
    headers = _build_headers(token)
    headers["Accept"] = "text/event-stream"
    payload = {
        "model": "coder-model",
        "messages": [
            {
                "role": "user",
                "content": "Hi there. What this project is all about?",
            }
        ],
        "stream": True,
        "max_tokens": 200,
        "extra_body": {"enable_thinking": False},
    }
    with httpx.Client(http2=True, timeout=60) as client:
        with client.stream("POST", url, headers=headers, json=payload) as r:
            print("stream_no_thinking status", r.status_code)
            printed = 0
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                print("sse", data[:240])
                printed += 1
                if data == "[DONE]" or printed >= 12:
                    break

    # Try streaming with tools (OpenAI-style function calling)
    tool_payload = {
        "model": "coder-model",
        "messages": [
            {
                "role": "user",
                "content": "Hi there. What this project is all about?",
            }
        ],
        "stream": True,
        "max_tokens": 200,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "No-op tool for testing.",
                    "parameters": {
                        "type": "object",
                        "properties": {"input": {"type": "string"}},
                    },
                },
            }
        ],
        "tool_choice": "auto",
    }
    with httpx.Client(http2=True, timeout=60) as client:
        with client.stream("POST", url, headers=headers, json=tool_payload) as r:
            print("stream_with_tools status", r.status_code)
            printed = 0
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                print("sse", data[:240])
                printed += 1
                if data == "[DONE]" or printed >= 12:
                    break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
