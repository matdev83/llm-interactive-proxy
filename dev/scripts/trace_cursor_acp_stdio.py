"""Trace raw JSON-RPC lines on Cursor CLI ACP stdio (RX/TX timing).

Usage (from repo root, with venv):

  .\\.venv\\Scripts\\python.exe dev/scripts/trace_cursor_acp_stdio.py ^
      --workspace C:\\path\\to\\repo --model composer-2 --prompt "Say hi in one word."

Requires ``agent`` (or ``CURSOR_AGENT_BIN``) on PATH and Cursor auth already
configured for ``agent acp``.

This script does not use the proxy stack; it speaks minimal ACP on stdio so you
can see which ``session/update`` kinds the CLI emits (e.g. ``agent_thought_chunk``,
``tool_call``) and the time between lines.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.connectors.cursor_cli_acp import (
    build_cursor_agent_acp_command,
    resolve_cursor_agent_executable,
)


def _log(direction: str, label: str, payload: Any, *, t0: float) -> None:
    now = time.monotonic()
    if isinstance(payload, dict):
        line = json.dumps(payload, ensure_ascii=False, default=str)
    else:
        line = str(payload)
    if len(line) > 500:
        line = line[:500] + "…"
    print(f"{now - t0:8.3f}s {direction} {label} {line}", flush=True)


async def _write_json(
    proc: asyncio.subprocess.Process, obj: dict[str, Any], t0: float
) -> None:
    assert proc.stdin is not None
    _log(
        "TX",
        obj.get("method", "?"),
        {"id": obj.get("id"), "method": obj.get("method")},
        t0=t0,
    )
    proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
    await proc.stdin.drain()


async def _run_session(
    *,
    workspace: Path,
    model: str,
    prompt: str,
    trust_workspace: bool,
    turn_timeout: float,
) -> int:
    exe = resolve_cursor_agent_executable(os.environ.get("CURSOR_AGENT_BIN"))
    if not exe:
        print(
            "Could not resolve Cursor agent executable (set CURSOR_AGENT_BIN).",
            file=sys.stderr,
        )
        return 2

    cmd = build_cursor_agent_acp_command(
        exe,
        model=model,
        trust_workspace=trust_workspace,
        extra_args=[],
        cursor_api_endpoint=os.environ.get("CURSOR_API_ENDPOINT"),
    )
    print("Command:", cmd, flush=True)

    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(workspace),
    )

    async def drain_until_jsonrpc_result(expect_id: int) -> dict[str, Any]:
        deadline = time.monotonic() + turn_timeout
        while time.monotonic() < deadline:
            assert proc.stdout is not None
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
            if not raw:
                return {}
            try:
                msg = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("method") == "session/update" and isinstance(
                msg.get("params"), dict
            ):
                upd = msg["params"].get("update") or {}
                kind = upd.get("sessionUpdate")
                _log("RX", "session/update", {"sessionUpdate": kind}, t0=t0)
                continue
            # Agent-initiated JSON-RPC request (must be answered for the turn to proceed).
            if (
                msg.get("method")
                and msg.get("id") is not None
                and "result" not in msg
                and "error" not in msg
            ):
                rid = msg["id"]
                _log("RX", f"server->{msg.get('method')}", {"id": rid}, t0=t0)
                await _write_json(
                    proc,
                    {"jsonrpc": "2.0", "id": rid, "result": {}},
                    t0,
                )
                continue
            if msg.get("method"):
                _log("RX", str(msg.get("method")), {"id": msg.get("id")}, t0=t0)
                continue
            if msg.get("id") == expect_id and ("result" in msg or "error" in msg):
                _log(
                    "RX",
                    "response",
                    {"id": msg.get("id"), "error": msg.get("error")},
                    t0=t0,
                )
                return msg
        raise TimeoutError(f"No response for id={expect_id}")

    try:
        i1 = 1
        await _write_json(
            proc,
            {
                "jsonrpc": "2.0",
                "id": i1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "acp-stdio-trace", "version": "1"},
                },
            },
            t0,
        )
        await drain_until_jsonrpc_result(i1)

        i2 = 2
        await _write_json(
            proc,
            {
                "jsonrpc": "2.0",
                "id": i2,
                "method": "authenticate",
                "params": {"methodId": "cursor_login"},
            },
            t0,
        )
        await drain_until_jsonrpc_result(i2)

        i3 = 3
        await _write_json(
            proc,
            {
                "jsonrpc": "2.0",
                "id": i3,
                "method": "session/new",
                "params": {"cwd": str(workspace.resolve()), "mcpServers": []},
            },
            t0,
        )
        sn = await drain_until_jsonrpc_result(i3)
        result = sn.get("result") or {}
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            print(f"session/new missing sessionId: {sn}", file=sys.stderr)
            return 1

        i4 = 4
        await _write_json(
            proc,
            {
                "jsonrpc": "2.0",
                "id": i4,
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": prompt}],
                    "messageId": "trace-1",
                },
            },
            t0,
        )

        # Stream updates until prompt response id matches.
        deadline = time.monotonic() + turn_timeout
        while time.monotonic() < deadline:
            assert proc.stdout is not None
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=30.0)
            if not raw:
                break
            try:
                msg = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("method") == "session/update" and isinstance(
                msg.get("params"), dict
            ):
                upd = msg["params"].get("update") or {}
                kind = upd.get("sessionUpdate")
                _log("RX", "session/update", {"sessionUpdate": kind}, t0=t0)
                continue
            if (
                msg.get("method")
                and msg.get("id") is not None
                and "result" not in msg
                and "error" not in msg
            ):
                rid = msg["id"]
                _log("RX", f"server->{msg.get('method')}", {"id": rid}, t0=t0)
                await _write_json(
                    proc,
                    {"jsonrpc": "2.0", "id": rid, "result": {}},
                    t0,
                )
                continue
            if msg.get("id") == i4 and ("result" in msg or "error" in msg):
                _log("RX", "prompt_done", {"id": i4, "error": msg.get("error")}, t0=t0)
                break
            if msg.get("method"):
                _log("RX", str(msg.get("method")), {"id": msg.get("id")}, t0=t0)

        proc.stdin.close()
        await asyncio.wait_for(proc.wait(), timeout=30.0)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        print(f"Timed out: {exc}", file=sys.stderr)
        proc.kill()
        return 1
    finally:
        if proc.stderr:
            err = await proc.stderr.read()
            if err:
                print(
                    "--- stderr ---",
                    err.decode("utf-8", errors="replace")[:4000],
                    flush=True,
                )

    return int(proc.returncode or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model", default="composer-2")
    parser.add_argument("--prompt", default="Reply with one short sentence.")
    parser.add_argument("--no-trust", action="store_true")
    parser.add_argument(
        "--turn-timeout",
        type=float,
        default=300.0,
        help="Max seconds waiting for session/new and prompt completion.",
    )
    args = parser.parse_args()
    ws = args.workspace.expanduser().resolve()
    if not ws.is_dir():
        print(f"workspace is not a directory: {ws}", file=sys.stderr)
        return 2

    return asyncio.run(
        _run_session(
            workspace=ws,
            model=args.model,
            prompt=args.prompt,
            trust_workspace=not args.no_trust,
            turn_timeout=args.turn_timeout,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
