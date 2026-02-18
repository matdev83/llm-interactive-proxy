#!/usr/bin/env python
"""
Side-by-side comparison of proxy-like vs gemini-cli-like requests to Code Assist.

Sends identical streamGenerateContent payloads using two header profiles:
  A) "proxy-like"      - python-requests default User-Agent + x-llmproxy-loop-guard
  B) "gemini-cli-like"  - GeminiCLI/... User-Agent, no extra headers

Reports status codes, response times, Retry-After headers and 429 occurrences
for each profile so you can see whether headers influence rate-limiting.

Usage:
    .venv\\Scripts\\python.exe dev/scripts/compare_proxy_vs_gemini_cli.py
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

OAUTH_CLIENT_ID = "".join(
    ["681255809395-", "oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"]
)
OAUTH_CLIENT_SECRET = "".join(["GOCSPX-", "4uHgMPm-1o7Sk-geV6Cu5clXFsxl"])
TOKEN_URL = "https://oauth2.googleapis.com/token"

BASE_URL = os.getenv(
    "CODE_ASSIST_ENDPOINT", "https://cloudcode-pa.googleapis.com"
)
STREAM_URL = f"{BASE_URL}/v1internal:streamGenerateContent"
LOAD_URL = f"{BASE_URL}/v1internal:loadCodeAssist"

ROUNDS = 5
PROMPT = "Say 'OK' and nothing else."
MODEL = os.getenv("CODE_ASSIST_MODEL", "gemini-2.5-flash")

GEMINI_CLI_UA = (
    f"GeminiCLI/0.11.0-nightly ({platform.system().lower()}; "
    f"{platform.machine().lower()})"
)


def _refresh_access_token(refresh_token: str) -> str:
    """Use the refresh_token to obtain a fresh access_token."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _load_first_account() -> tuple[str, str | None]:
    """Load (and refresh) an OAuth access_token from the first account file.

    Returns (access_token, project_id).
    """
    accounts_dir = PROJECT_ROOT / "var" / "gemini_oauth_accounts"
    if not accounts_dir.is_dir():
        sys.exit(f"No accounts directory at {accounts_dir}")
    for p in sorted(accounts_dir.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        refresh_tok = data.get("refresh_token")
        if refresh_tok:
            print(f"Using account: {p.stem} (refreshing token...)")
            token = _refresh_access_token(refresh_tok)
            project_id = data.get("project_id")
            return token, project_id
    sys.exit("No account with refresh_token found")


def _discover_project(token: str, extra_headers: dict[str, str]) -> str:
    """Call loadCodeAssist to get the GCP project."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        **extra_headers,
    }
    payload = {
        "metadata": {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
        }
    }
    resp = requests.post(LOAD_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json().get("cloudaicompanionProject", "default")


def _build_request_body(
    model: str, project: str, session_id: str
) -> dict:
    """Build a standard streamGenerateContent body matching gemini-cli shape."""
    return {
        "model": model,
        "project": project,
        "user_prompt_id": f"{session_id}########1",
        "request": {
            "contents": [
                {"role": "user", "parts": [{"text": PROMPT}]}
            ],
            "session_id": session_id,
        },
    }


def _send_request(
    token: str,
    body: dict,
    extra_headers: dict[str, str],
    label: str,
) -> dict:
    """Fire one streaming request and return a result summary dict."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        **extra_headers,
    }
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            STREAM_URL,
            params={"alt": "sse"},
            headers=headers,
            json=body,
            timeout=60,
            stream=True,
        )
        status = resp.status_code
        retry_after = resp.headers.get("Retry-After")
        body_preview = ""
        for chunk in resp.iter_content(chunk_size=4096):
            body_preview += chunk.decode("utf-8", errors="replace")
            if len(body_preview) > 800:
                break
        resp.close()
    except Exception as exc:
        status = -1
        retry_after = None
        body_preview = str(exc)

    elapsed = time.perf_counter() - t0
    return {
        "label": label,
        "status": status,
        "elapsed_ms": int(elapsed * 1000),
        "retry_after": retry_after,
        "body_preview": body_preview[:300],
    }


def _print_result(r: dict) -> None:
    tag = "[429!]" if r["status"] == 429 else f"[{r['status']}]"
    ra = f"  Retry-After={r['retry_after']}" if r["retry_after"] else ""
    print(
        f"  {tag} {r['label']:20s}  {r['elapsed_ms']:>5d}ms{ra}"
    )
    if r["status"] not in (200, -1):
        print(f"       body: {r['body_preview']}")


def main() -> None:
    token, stored_project = _load_first_account()
    session_id = uuid.uuid4().hex[:12]

    profiles: dict[str, dict[str, str]] = {
        "proxy-like": {
            "x-llmproxy-loop-guard": "1",
            # leave User-Agent as default python-requests/...
        },
        "gemini-cli-like": {
            "User-Agent": GEMINI_CLI_UA,
        },
    }

    print("=" * 66)
    print("Code Assist Header Comparison")
    print("=" * 66)
    print(f"Endpoint : {STREAM_URL}")
    print(f"Model    : {MODEL}")
    print(f"Rounds   : {ROUNDS}")
    print(f"Session  : {session_id}")
    print()

    for name, hdrs in profiles.items():
        print(f"--- Profile: {name} ---")
        merged = {
            "Authorization": f"Bearer {token[:8]}...",
            "Content-Type": "application/json",
            **hdrs,
        }
        for k, v in merged.items():
            print(f"  {k}: {v}")
        print()

    if stored_project:
        project = stored_project
        print(f"Project  : {project} (from account file)\n")
    else:
        project = _discover_project(token, {"User-Agent": GEMINI_CLI_UA})
        print(f"Project  : {project} (from loadCodeAssist)\n")

    body = _build_request_body(MODEL, project, session_id)
    print(f"Request body (shared):")
    sanitised = {**body}
    print(f"  {json.dumps(sanitised, indent=2)[:400]}\n")

    stats: dict[str, list[dict]] = {name: [] for name in profiles}

    for i in range(1, ROUNDS + 1):
        print(f"Round {i}/{ROUNDS}")
        for name, hdrs in profiles.items():
            r = _send_request(token, body, hdrs, name)
            stats[name].append(r)
            _print_result(r)
        print()
        if i < ROUNDS:
            time.sleep(1)

    print("=" * 66)
    print("Summary")
    print("=" * 66)
    for name, results in stats.items():
        total = len(results)
        ok = sum(1 for r in results if r["status"] == 200)
        rate_limited = sum(1 for r in results if r["status"] == 429)
        errors = sum(1 for r in results if r["status"] not in (200, 429))
        avg_ms = (
            sum(r["elapsed_ms"] for r in results if r["status"] == 200) // max(ok, 1)
        )
        print(
            f"  {name:20s}  ok={ok}/{total}  429={rate_limited}  "
            f"err={errors}  avg_ok={avg_ms}ms"
        )
    print()


if __name__ == "__main__":
    main()
