"""Request/response pair analysis for capture entries."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from src.core.wire_capture.inspection.correlation import (
    collect_backend_chunks_for_cp,
    collect_client_chunks_for_cp,
    compute_backend_duration,
    compute_backend_ttft,
)
from src.core.wire_capture.inspection.payload import parse_all_sse_events
from src.core.wire_capture.inspection.text_output import writeln


def analyze_request_response_pairs(
    entries: list[dict[str, Any]],
    *,
    out: TextIO | None = None,
    backend_filter: str | None = None,
) -> None:
    """Analyze request/response pairs and print findings to ``out``."""
    out = out or sys.stdout
    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, "REQUEST/RESPONSE ANALYSIS")
    writeln(out, "=" * 70)
    if backend_filter:
        writeln(out, f"(Filtered to backend: {backend_filter})")
        writeln(out, "=" * 70)

    request_num = 0
    i = 0

    while i < len(entries):
        e = entries[i]

        if e["dir"] == 0:
            backend_entries = collect_backend_chunks_for_cp(entries, i)
            if backend_filter is not None:
                backend_entries = [
                    entry
                    for entry in backend_entries
                    if entry.get("meta", {}).get("be") == backend_filter
                ]
            if backend_filter is not None and not backend_entries:
                i += 1
                continue

            request_num += 1
            writeln(out, f"\n--- REQUEST #{request_num} ---")

            try:
                req = json.loads(e["data"].decode("utf-8"))
                model = req.get("model", "N/A")
                writeln(out, f"Model: {model}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                writeln(out, "Model: (could not parse)")

            client_entries = collect_client_chunks_for_cp(entries, i)
            client_chunks = [entry.get("data", b"") for entry in client_entries]

            backend_content_len = 0
            backend_tool_calls = 0
            backend_tool_names: set[str] = set()
            backend_models: set[str] = set()
            issues: list[str] = []

            if backend_entries:
                ttft = compute_backend_ttft(e, backend_entries)
                duration = compute_backend_duration(e, backend_entries)
                timing_parts: list[str] = []
                if ttft is not None:
                    timing_parts.append(f"TTFT={ttft:.3f}s")
                if duration is not None:
                    timing_parts.append(f"Duration={duration:.3f}s")
                if timing_parts:
                    writeln(out, f"Timing: {', '.join(timing_parts)}")

            for entry in backend_entries:
                chunk = entry["data"]
                events = parse_all_sse_events(chunk)

                if not events and chunk.strip().startswith(b"{"):
                    try:
                        error_json = json.loads(chunk)
                        if "error" in error_json:
                            issues.append(
                                "Backend Error: "
                                f"{error_json['error'].get('message', 'Unknown error')}"
                            )
                            events.append(error_json)
                    except json.JSONDecodeError:
                        pass

                for parsed in events:
                    model = parsed.get("model", "")
                    if model:
                        backend_models.add(model)

                    usage = parsed.get("usage", {})
                    if usage and usage.get("completion_tokens", 0) == 0:
                        issues.append("Usage-only chunk (completion_tokens=0)")

                    choices = parsed.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            backend_content_len += len(content)

                        tool_calls = delta.get("tool_calls")
                        if tool_calls:
                            backend_tool_calls += len(tool_calls)
                            for tc in tool_calls:
                                if "function" in tc and "name" in tc["function"]:
                                    backend_tool_names.add(tc["function"]["name"])

                        if (
                            choice.get("finish_reason") == "stop"
                            and backend_content_len == 0
                            and backend_tool_calls == 0
                        ):
                            issues.append("Immediate stop without content")

                    msg_id = parsed.get("id", "")
                    if "fallback" in msg_id:
                        issues.append("Fallback mechanism activated")

            writeln(out, f"Backend models: {backend_models or 'N/A'}")
            backend_info = f"{backend_content_len} chars"
            if backend_tool_calls:
                tool_names_str = (
                    f" ({', '.join(sorted(backend_tool_names))})"
                    if backend_tool_names
                    else ""
                )
                backend_info += f", {backend_tool_calls} tool_calls{tool_names_str}"
            writeln(out, f"Backend content: {backend_info}")

            client_content_len = 0
            client_tool_calls = 0
            client_has_finish = False
            client_has_data = False
            client_chunk_sizes = [len(c) for c in client_chunks]
            for chunk in client_chunks:
                if not chunk:
                    continue
                chunk_text = chunk.decode("utf-8", errors="replace").strip()
                if chunk_text and chunk_text != "data: [DONE]":
                    client_has_data = True

                events = parse_all_sse_events(chunk)
                for parsed in events:
                    client_model = parsed.get("model", "")
                    if client_model and "code-assist" in client_model.lower():
                        issues.append(
                            f"Internal model name leak to client: {client_model}"
                        )

                    choices = parsed.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        client_content_len += len(content)
                        tool_calls = delta.get("tool_calls")
                        if tool_calls:
                            client_tool_calls += len(tool_calls)
                        if choice.get("finish_reason"):
                            client_has_finish = True

            client_info = f"{client_content_len} chars"
            if client_tool_calls:
                client_info += f", {client_tool_calls} tool_calls"
            if client_has_finish:
                client_info += ", finish_reason"
            if not client_has_data and not client_has_finish:
                client_info = "(no data, only [DONE])"
            nonzero_chunks = [s for s in client_chunk_sizes if s > 0]
            if nonzero_chunks:
                client_info += f" [{','.join(str(s) for s in nonzero_chunks)}]"
            writeln(out, f"Client received: {client_info}")

            if issues:
                writeln(out, "ISSUES:")
                for issue in set(issues):
                    writeln(out, f"  [!] {issue}")

            i += 1
        else:
            i += 1
