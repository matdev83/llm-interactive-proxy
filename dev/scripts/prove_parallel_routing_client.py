"""Minimal streaming client for proving parallel routing behavior.

Usage:
  ./.venv/Scripts/python.exe dev/scripts/prove_parallel_routing_client.py \
    --base-url http://127.0.0.1:8000 \
    --model "[handicap=15]nvidia:moonshotai/kimi-k2.6![handicap=10]nvidia:minimaxai/minimax-m3!nvidia:nvidia/nemotron-3-ultra-550b-a55b"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.app.application_builder import build_app_async
from src.core.config.app_config import load_config

DEFAULT_MODEL = (
    "[handicap=15]nvidia:moonshotai/kimi-k2.6!"
    "[handicap=10]nvidia:minimaxai/minimax-m3!"
    "nvidia:nvidia/nemotron-3-ultra-550b-a55b"
)


def _extract_delta_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    if isinstance(content, str):
        return content
    return ""


def _build_payload(model: str, prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0,
        "max_tokens": 80,
    }
    return payload


def _add_tool_probe(payload: dict[str, Any]) -> None:
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "tell_joke_route",
                "description": "Report the winning route in a funny way.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "winner": {"type": "string"},
                        "joke": {"type": "string"},
                    },
                    "required": ["winner", "joke"],
                },
            },
        }
    ]
    payload["tool_choice"] = {
        "type": "function",
        "function": {"name": "tell_joke_route"},
    }


def _reasoning_from_container(container: dict[str, Any]) -> str:
    for key in ("reasoning_content", "reasoning", "thinking", "thought"):
        value = container.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _print_non_streaming_result(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return 2
    first = choices[0]
    if not isinstance(first, dict):
        return 2
    message = first.get("message")
    if not isinstance(message, dict):
        return 2
    content = message.get("content")
    reasoning = _reasoning_from_container(message)
    tool_calls = message.get("tool_calls")
    print("summary:")
    print(f"  model={payload.get('model')!r}")
    print(f"  content={content!r}")
    print(f"  reasoning_present={bool(reasoning)}")
    if reasoning:
        print(f"  reasoning_prefix={reasoning[:300]!r}")
    print(f"  tool_calls_present={isinstance(tool_calls, list) and bool(tool_calls)}")
    if isinstance(tool_calls, list):
        print(f"  tool_calls={json.dumps(tool_calls, ensure_ascii=True)}")
    return 0 if (content or reasoning or tool_calls) else 2


def _print_stream_line(
    *,
    line: str,
    elapsed: float,
    first_data_at: float | None,
    first_content_at: float | None,
    content_parts: list[str],
    reasoning_parts: list[str],
    tool_call_events: list[Any],
) -> tuple[float | None, float | None, bool]:
    if not line:
        return first_data_at, first_content_at, False
    if line.startswith(":"):
        print(f"{elapsed:8.3f}s keepalive {line}")
        return first_data_at, first_content_at, False
    if not line.startswith("data: "):
        print(f"{elapsed:8.3f}s raw {line}")
        return first_data_at, first_content_at, False

    data = line[6:]
    if first_data_at is None:
        first_data_at = elapsed
    if data == "[DONE]":
        print(f"{elapsed:8.3f}s done")
        return first_data_at, first_content_at, True

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        print(f"{elapsed:8.3f}s data {data}")
        return first_data_at, first_content_at, False

    text = _extract_delta_text(parsed)
    choices = parsed.get("choices")
    delta: dict[str, Any] = {}
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        raw_delta = choices[0].get("delta")
        if isinstance(raw_delta, dict):
            delta = raw_delta
    reasoning = _reasoning_from_container(delta)
    if reasoning:
        reasoning_parts.append(reasoning)
        print(f"{elapsed:8.3f}s reasoning {reasoning[:240]!r}")
    tool_calls = delta.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        tool_call_events.append(tool_calls)
        print(f"{elapsed:8.3f}s tool_calls {json.dumps(tool_calls, ensure_ascii=True)}")
    if text:
        if first_content_at is None:
            first_content_at = elapsed
            print(f"{elapsed:8.3f}s first-content {text!r}")
        else:
            print(f"{elapsed:8.3f}s content {text!r}")
        content_parts.append(text)
    else:
        print(f"{elapsed:8.3f}s data {data[:240]}")
    return first_data_at, first_content_at, False


async def _run_in_process(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    app = await build_app_async(config)
    transport = httpx.ASGITransport(app=app)
    payload = _build_payload(args.model, args.prompt)
    payload["stream"] = args.stream
    if args.tool_probe:
        _add_tool_probe(payload)
    timeout = httpx.Timeout(connect=10.0, read=args.timeout, write=30.0, pool=10.0)

    print("POST asgi://proxy/v1/chat/completions")
    print(f"model={args.model}")
    print(f"stream={args.stream}")
    print(f"tool_probe={args.tool_probe}")

    if not args.stream:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://asgi.local",
            timeout=timeout,
        ) as client:
            response = await client.post("/v1/chat/completions", json=payload)
            print(f"status={response.status_code}")
            if response.status_code >= 400:
                print(response.text)
                return 1
            return _print_non_streaming_result(response.json())

    started = time.perf_counter()
    first_data_at: float | None = None
    first_content_at: float | None = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_call_events: list[Any] = []

    async with (
        httpx.AsyncClient(
            transport=transport,
            base_url="http://asgi.local",
            timeout=timeout,
        ) as client,
        client.stream("POST", "/v1/chat/completions", json=payload) as response,
    ):
        print(f"status={response.status_code}")
        if response.status_code >= 400:
            print((await response.aread()).decode("utf-8", errors="replace"))
            return 1

        async for line in response.aiter_lines():
            elapsed = time.perf_counter() - started
            first_data_at, first_content_at, done = _print_stream_line(
                line=line,
                elapsed=elapsed,
                first_data_at=first_data_at,
                first_content_at=first_content_at,
                content_parts=content_parts,
                reasoning_parts=reasoning_parts,
                tool_call_events=tool_call_events,
            )
            if done:
                break

    print("summary:")
    print(f"  first_data_seconds={first_data_at}")
    print(f"  first_content_seconds={first_content_at}")
    print(f"  content={''.join(content_parts)!r}")
    print(f"  reasoning_present={bool(reasoning_parts)}")
    if reasoning_parts:
        print(f"  reasoning_prefix={''.join(reasoning_parts)[:300]!r}")
    print(f"  tool_calls_present={bool(tool_call_events)}")
    if tool_call_events:
        print(f"  tool_call_events={json.dumps(tool_call_events, ensure_ascii=True)}")
    return 0 if (content_parts or reasoning_parts or tool_call_events) else 2


def _run_network(args: argparse.Namespace) -> int:
    url = args.base_url.rstrip("/") + "/v1/chat/completions"
    payload = _build_payload(args.model, args.prompt)
    payload["stream"] = args.stream
    if args.tool_probe:
        _add_tool_probe(payload)
    timeout = httpx.Timeout(connect=10.0, read=args.timeout, write=30.0, pool=10.0)

    print(f"POST {url}")
    print(f"model={args.model}")
    print(f"stream={args.stream}")
    print(f"tool_probe={args.tool_probe}")

    if not args.stream:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            print(f"status={response.status_code}")
            if response.status_code >= 400:
                print(response.text)
                return 1
            return _print_non_streaming_result(response.json())

    started = time.perf_counter()
    first_data_at: float | None = None
    first_content_at: float | None = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_call_events: list[Any] = []

    with (
        httpx.Client(timeout=timeout) as client,
        client.stream("POST", url, json=payload) as response,
    ):
        print(f"status={response.status_code}")
        if response.status_code >= 400:
            print(response.read().decode("utf-8", errors="replace"))
            return 1

        for line in response.iter_lines():
            elapsed = time.perf_counter() - started
            first_data_at, first_content_at, done = _print_stream_line(
                line=line,
                elapsed=elapsed,
                first_data_at=first_data_at,
                first_content_at=first_content_at,
                content_parts=content_parts,
                reasoning_parts=reasoning_parts,
                tool_call_events=tool_call_events,
            )
            if done:
                break

    print("summary:")
    print(f"  first_data_seconds={first_data_at}")
    print(f"  first_content_seconds={first_content_at}")
    print(f"  content={''.join(content_parts)!r}")
    print(f"  reasoning_present={bool(reasoning_parts)}")
    if reasoning_parts:
        print(f"  reasoning_prefix={''.join(reasoning_parts)[:300]!r}")
    print(f"  tool_calls_present={bool(tool_call_events)}")
    if tool_call_events:
        print(f"  tool_call_events={json.dumps(tool_call_events, ensure_ascii=True)}")
    return 0 if (content_parts or reasoning_parts or tool_call_events) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove proxy parallel routing via SSE")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--prompt",
        default="Reply with one short sentence identifying yourself as the winning route.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--stream", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--tool-probe", action="store_true")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Build the FastAPI app in-process instead of connecting to a server.",
    )
    parser.add_argument(
        "--config",
        default="dev/config/parallel_routing_nvidia.yaml",
        help="Config file used with --in-process.",
    )
    args = parser.parse_args()

    if args.in_process:
        return asyncio.run(_run_in_process(args))
    return _run_network(args)


if __name__ == "__main__":
    raise SystemExit(main())
