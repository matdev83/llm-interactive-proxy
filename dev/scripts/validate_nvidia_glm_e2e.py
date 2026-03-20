#!/usr/bin/env python3
"""End-to-end validation: spawn the proxy with the Nvidia backend, list models, demo-model chat.

Prerequisites
-------------
- ``NVIDIA_API_KEY`` set to a **valid NVIDIA Build inference API key** (typically ``nvapi-...``),
  passed through to the child proxy process. Leading/trailing whitespace and a redundant
  ``Bearer ``-prefixed value are normalized automatically (see ``NvidiaConnector.initialize``).
- Network access to ``https://integrate.api.nvidia.com`` from the machine running this script.

Important
---------
NVIDIA's ``GET /v1/models`` catalog is often reachable **without** authentication; **chat
completions** still require a key with **inference** rights for the chosen model (enable the model on
NVIDIA Build if you see 401). If you are sure the key is valid, confirm it is an inference key
(not another token type) and that the model is enabled for your account.

Automated proof without live NVIDIA credentials: run
``pytest tests/integration/test_nvidia_backend_http_e2e.py`` (mocks the upstream API).

Environment (optional)
----------------------
``NV_E2E_PORT``           Bind port for the temporary proxy (default: 28765).
``NV_E2E_UPSTREAM_MODEL``  Upstream NVIDIA model id (default: ``stepfun-ai/step-3.5-flash``).
``NV_E2E_BASE_URL``       Proxy URL if testing against an already-running instance (skips spawn).

Exit code 0 only when ``GET /v1/models`` on the proxy succeeds and a non-streaming chat completion
returns assistant content for ``nvidia:<upstream>`` through the proxy.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]


def _normalize_nvidia_api_key(value: str) -> str:
    """Match ``src.connectors.nvidia._normalize_nvidia_api_key`` (keep script standalone)."""

    s = value.strip()
    lower = s.lower()
    if lower.startswith("bearer "):
        s = s[7:].lstrip()
    return s


DEFAULT_UPSTREAM = "stepfun-ai/step-3.5-flash"
DEFAULT_PORT = 28765
STARTUP_TIMEOUT_S = 120.0
HTTP_TIMEOUT_S = 300.0


def _venv_python(repo: Path) -> Path:
    if sys.platform == "win32":
        candidate = repo / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = repo / ".venv" / "bin" / "python"
    return candidate if candidate.is_file() else Path(sys.executable)


def _pick_free_port(preferred: int) -> int:
    if preferred > 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_min_config(path: Path, port: int) -> None:
    text = f"""host: "127.0.0.1"
port: {port}
auth:
  disable_auth: true
logging:
  level: WARNING
backends:
  nvidia:
    timeout: 300
"""
    path.write_text(text, encoding="utf-8")


def _wait_for_proxy(base: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    last_err: str | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base}/v1/models", timeout=5.0)
            if r.status_code == 200:
                return
            last_err = f"HTTP {r.status_code}"
        except OSError as e:
            last_err = str(e)
        except httpx.HTTPError as e:
            last_err = str(e)
        time.sleep(0.4)
    raise RuntimeError(f"Proxy did not become ready at {base}: {last_err}")


def _resolve_listed_nvidia_model(
    models_payload: dict[str, Any],
    upstream_want: str,
) -> str | None:
    """Return full proxy model id (e.g. nvidia:stepfun-ai/step-3.5-flash) or None."""
    data = models_payload.get("data")
    if not isinstance(data, list):
        return None

    want_norm = upstream_want.replace("_", ".").lower()
    nvidia_candidates: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        mid = item.get("id")
        if not isinstance(mid, str):
            continue
        if not mid.startswith("nvidia:"):
            continue
        suffix = mid.split(":", 1)[1]
        suffix_norm = suffix.replace("_", ".").lower()
        nvidia_candidates.append(mid)
        if suffix == upstream_want or suffix_norm == want_norm:
            return mid

    explicit = f"nvidia:{upstream_want}"
    if explicit in nvidia_candidates:
        return explicit

    return None


def main() -> int:
    raw_key = os.environ.get("NVIDIA_API_KEY")
    if not raw_key or not raw_key.strip():
        print(
            "ERROR: NVIDIA_API_KEY is not set. Export it before running this script.",
            file=sys.stderr,
        )
        return 2

    # Normalize once so the child process and any direct probes use the same value as the connector.
    os.environ["NVIDIA_API_KEY"] = _normalize_nvidia_api_key(raw_key)

    upstream = os.environ.get("NV_E2E_UPSTREAM_MODEL", DEFAULT_UPSTREAM).strip()
    existing = os.environ.get("NV_E2E_BASE_URL", "").strip().rstrip("/")

    proc: subprocess.Popen[bytes] | None = None
    cfg_path: Path | None = None

    try:
        if existing:
            base = existing
            print(f"Using existing proxy at {base}")
        else:
            preferred = int(os.environ.get("NV_E2E_PORT", str(DEFAULT_PORT)))
            port = _pick_free_port(preferred)
            base = f"http://127.0.0.1:{port}"

            fd, cfg_str = tempfile.mkstemp(suffix=".yaml", text=True)
            os.close(fd)
            cfg_path = Path(cfg_str)
            _write_min_config(cfg_path, port)

            py = str(_venv_python(REPO_ROOT))

            cmd = [
                py,
                "-m",
                "src.core.cli",
                "--config",
                str(cfg_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--disable-auth",
            ]
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            if not (env.get("NVIDIA_API_KEY") or "").strip():
                print(
                    "ERROR: NVIDIA_API_KEY missing from env passed to child proxy process.",
                    file=sys.stderr,
                )
                return 2

            print("Spawning proxy:", " ".join(cmd))
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _wait_for_proxy(base)
            print(f"Proxy ready at {base}")

        client = httpx.Client(base_url=base, timeout=HTTP_TIMEOUT_S)

        print("GET /v1/models ...")
        try:
            mr = client.get("/v1/models")
            mr.raise_for_status()
        except httpx.HTTPStatusError as e:
            print(e.response.text, file=sys.stderr)
            print(
                f"Model listing failed: HTTP {e.response.status_code}", file=sys.stderr
            )
            return 3
        models_json = mr.json()
        assert isinstance(models_json, dict)

        all_ids: list[str] = []
        for x in models_json.get("data", []):
            if not isinstance(x, dict):
                continue
            mid = x.get("id")
            if isinstance(mid, str):
                all_ids.append(mid)
        nvidia_ids = [i for i in all_ids if i.startswith("nvidia:")]
        print(f"Listed {len(all_ids)} models ({len(nvidia_ids)} nvidia-prefixed).")
        sys.stdout.flush()
        if nvidia_ids:
            preview = nvidia_ids[:80]
            print("Nvidia model ids (preview, up to 80):")
            print(json.dumps(preview, indent=2))
            sys.stdout.flush()

        model_id = _resolve_listed_nvidia_model(models_json, upstream)
        if not model_id:
            model_id = f"nvidia:{upstream}"
            print(
                f"No listing match for {upstream!r}; trying canonical id {model_id!r} anyway.",
            )
        else:
            print(f"Selected listed model: {model_id}")

        body = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Reply with a single line: 'Step-3.5-Flash via Nvidia backend OK' "
                        "and nothing else."
                    ),
                }
            ],
            "max_tokens": 64,
            "temperature": 0.2,
            "stream": False,
        }

        print("POST /v1/chat/completions ...")
        try:
            cr = client.post("/v1/chat/completions", json=body)
            cr.raise_for_status()
        except httpx.HTTPStatusError as e:
            print(e.response.text, file=sys.stderr)
            print(
                f"Chat completion failed: HTTP {e.response.status_code}. "
                f"Check NVIDIA_API_KEY and that your account can access {upstream!r}.",
                file=sys.stderr,
            )
            return 6
        chat = cr.json()
        assert isinstance(chat, dict)
        choices = chat.get("choices")
        if not isinstance(choices, list) or not choices:
            print("Invalid completion shape:", json.dumps(chat, indent=2)[:2000])
            return 4
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = (
            msg.get("content")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str)
            else None
        )
        if not content:
            print("No assistant content:", json.dumps(chat, indent=2)[:2000])
            return 5

        print("--- assistant output ---")
        print(content.strip())
        print("--- end ---")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if cfg_path is not None:
            with contextlib.suppress(OSError):
                cfg_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
