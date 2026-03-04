"""
Minimal test using curl subprocess (different TLS fingerprint than Python).
If curl works but httpx doesn't → TLS fingerprinting is the cause.
"""
import json
import platform
import subprocess
import sys
from pathlib import Path


def main() -> None:
    creds = json.loads((Path.home() / ".qwen" / "oauth_creds.json").read_text("utf-8"))
    token: str = creds["access_token"]
    ua: str = f"QwenCode/0.9.0 ({platform.system()}; {platform.machine()})"

    payload: str = json.dumps({
        "model": "coder-model",
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 5,
        "stream": False,
    })

    # Use curl.exe (not PowerShell alias) with identical headers to qwen-code
    cmd: list[str] = [
        "curl.exe", "-s",
        "-X", "POST",
        "https://portal.qwen.ai/v1/chat/completions",
        "-H", f"Content-Type: application/json",
        "-H", f"Authorization: Bearer {token}",
        "-H", f"User-Agent: {ua}",
        "-H", f"X-DashScope-CacheControl: enable",
        "-H", f"X-DashScope-UserAgent: {ua}",
        "-H", f"X-DashScope-AuthType: qwen-oauth",
        "-d", payload,
        "-w", "\n---HTTP_STATUS:%{http_code}---",
    ]

    print("=== CURL TEST (different TLS stack) ===")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    output = result.stdout
    print(f"stdout: {output[:500]}")
    if result.stderr:
        print(f"stderr: {result.stderr[:200]}")
    print()

    # Now the same with httpx for comparison
    print("=== HTTPX TEST (Python TLS stack) ===")
    import httpx
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": ua,
        "X-DashScope-CacheControl": "enable",
        "X-DashScope-UserAgent": ua,
        "X-DashScope-AuthType": "qwen-oauth",
    }
    try:
        resp = httpx.post(
            "https://portal.qwen.ai/v1/chat/completions",
            content=payload.encode(),
            headers=headers,
            timeout=15.0,
        )
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text[:300]}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
