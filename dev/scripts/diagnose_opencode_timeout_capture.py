"""Inspect OpenCode bash timeout propagation in a CBOR capture.

This is a focused diagnostic helper for the openai-codex/OpenCode timeout loop.
It streams the capture to avoid loading large files into memory.
"""

from __future__ import annotations

import argparse
import json
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import cbor2

CLIENT_TO_PROXY = 0
PROXY_TO_CLIENT = 1
PROXY_TO_BACKEND = 2
BACKEND_TO_PROXY = 3


def _decode_entry_data(entry: dict[str, Any]) -> bytes:
    data = entry["data"]
    if entry.get("enc") == "zlib":
        return cast(bytes, zlib.decompress(data))
    return cast(bytes, data)


def _json_body(raw: bytes) -> Any | None:
    body = raw
    if b"\r\n\r\n" in raw:
        body = raw.split(b"\r\n\r\n", 1)[1]
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _iter_sse_json(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace")
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            events.append(decoded)
    return events


def _find_tool(tools: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(tools, list):
        return None
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_name = tool.get("name")
        function = tool.get("function")
        if not tool_name and isinstance(function, dict):
            tool_name = function.get("name")
        if tool_name == name:
            return tool
    return None


def _tool_parameters(tool: dict[str, Any] | None) -> dict[str, Any]:
    if not tool:
        return {}
    params = tool.get("parameters")
    function = tool.get("function")
    if params is None and isinstance(function, dict):
        params = function.get("parameters")
    return params if isinstance(params, dict) else {}


def _summarize_bash_schema(payload: dict[str, Any]) -> dict[str, Any] | None:
    tool = _find_tool(payload.get("tools"), "bash")
    if tool is None:
        tool = _find_tool(payload.get("tools"), "shell")
    if tool is None:
        return None
    params = _tool_parameters(tool)
    properties = params.get("properties") if isinstance(params, dict) else None
    if not isinstance(properties, dict):
        properties = {}
    return {
        "tool_name": tool.get("name")
        or (
            tool.get("function", {}).get("name")
            if isinstance(tool.get("function"), dict)
            else None
        ),
        "required": params.get("required"),
        "property_names": sorted(properties),
        "timeout_schema": properties.get("timeout"),
        "additionalProperties": params.get("additionalProperties"),
    }


def _append_tool_delta(
    tool_buffers: dict[str, dict[str, str]],
    event: dict[str, Any],
) -> None:
    choices = event.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        tool_calls = delta.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            key = str(tool_call.get("id") or tool_call.get("index") or "unknown")
            buf = tool_buffers[key]
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if isinstance(name, str):
                buf["name"] = name
            args_delta = function.get("arguments")
            if isinstance(args_delta, str):
                buf["arguments"] = buf.get("arguments", "") + args_delta


def _extract_responses_output_item(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "response.output_item.done":
        return None
    item = event.get("item")
    return item if isinstance(item, dict) else None


def diagnose(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "client_bash_schema": None,
        "backend_bash_schema": None,
        "backend_bridge_mentions_timeout": None,
        "backend_bridge_mentions_command_description_only": None,
        "client_bash_tool_call_summary": None,
        "backend_bash_output_item_summary": None,
    }
    client_tool_buffers: dict[str, dict[str, str]] = defaultdict(dict)
    backend_bash_output_items: list[dict[str, Any]] = []

    with path.open("rb") as f:
        cbor2.load(f)
        while True:
            try:
                entry = cbor2.load(f)
            except EOFError:
                break
            except cbor2.CBORDecodeEOF:
                break
            if not isinstance(entry, dict):
                continue
            direction = entry.get("dir")
            raw = _decode_entry_data(entry)

            if direction == CLIENT_TO_PROXY and result["client_bash_schema"] is None:
                payload = _json_body(raw)
                if (
                    isinstance(payload, dict)
                    and "opencode" in raw.decode("utf-8", errors="ignore").lower()
                ):
                    result["client_bash_schema"] = _summarize_bash_schema(payload)

            if direction == PROXY_TO_BACKEND and result["backend_bash_schema"] is None:
                meta_value = entry.get("meta")
                meta: dict[str, Any] = (
                    meta_value if isinstance(meta_value, dict) else {}
                )
                if meta.get("be") != "openai-codex":
                    continue
                payload = _json_body(raw)
                if not isinstance(payload, dict):
                    continue
                result["backend_bash_schema"] = _summarize_bash_schema(payload)
                instructions = payload.get("instructions")
                if isinstance(instructions, str):
                    result["backend_bridge_mentions_timeout"] = (
                        "timeout" in instructions
                    )
                    result["backend_bridge_mentions_command_description_only"] = (
                        "`command` and string `description`" in instructions
                    )

            if direction == PROXY_TO_CLIENT:
                for event in _iter_sse_json(raw):
                    _append_tool_delta(client_tool_buffers, event)

            if direction == BACKEND_TO_PROXY:
                for event in _iter_sse_json(raw):
                    item = _extract_responses_output_item(event)
                    if not item:
                        continue
                    item_type = item.get("type")
                    name = item.get("name")
                    if item_type in {"function_call", "local_shell_call"} and name in {
                        "bash",
                        "shell",
                    }:
                        backend_bash_output_items.append(item)

    client_bash_tool_calls = [
        value
        for value in client_tool_buffers.values()
        if value.get("name") in {"bash", "shell"}
    ]

    def summarize_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
        parsed: list[dict[str, Any]] = []
        for call in calls:
            args = call.get("arguments")
            if not isinstance(args, str):
                continue
            try:
                decoded = json.loads(args)
            except json.JSONDecodeError:
                decoded = {"_unparseable": args}
            if not isinstance(decoded, dict):
                decoded = {"_decoded": decoded}
            parsed.append({"raw": call, "args": decoded})

        missing_timeout = [item for item in parsed if "timeout" not in item["args"]]
        description_mentions_timeout = [
            item
            for item in missing_timeout
            if "timeout" in str(item["args"].get("description", "")).lower()
        ]
        explicit_timeout_values = [
            item["args"].get("timeout") for item in parsed if "timeout" in item["args"]
        ]
        return {
            "total": len(parsed),
            "with_timeout": len(explicit_timeout_values),
            "without_timeout": len(missing_timeout),
            "without_timeout_but_description_mentions_timeout": len(
                description_mentions_timeout
            ),
            "explicit_timeout_values": sorted(
                {value for value in explicit_timeout_values if value is not None}
            ),
            "first_without_timeout_but_description_mentions_timeout": (
                description_mentions_timeout[0]
                if description_mentions_timeout
                else None
            ),
            "last_three_calls": parsed[-3:],
        }

    result["client_bash_tool_call_summary"] = summarize_calls(client_bash_tool_calls)
    result["backend_bash_output_item_summary"] = summarize_calls(
        backend_bash_output_items
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_file", type=Path)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.capture_file), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
