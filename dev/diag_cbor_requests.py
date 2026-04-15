"""Diagnose openai-codex quota inflation by analyzing CBOR wire captures.

Reads the most recent capture file, extracts PROXY_TO_BACKEND requests,
and examines request shapes for prompt_cache_key stability, input sizes,
instructions length, and store/previous_response_id fields.
"""

from __future__ import annotations

import json
import os
import sys
import zlib
from typing import Any

import cbor2

CBOR_DIR = "var/wire_captures_cbor"

DIRECTION_CLIENT_TO_PROXY = 0
DIRECTION_PROXY_TO_CLIENT = 1
DIRECTION_PROXY_TO_BACKEND = 2
DIRECTION_BACKEND_TO_PROXY = 3


def validate_header(header: dict[str, Any]) -> None:
    magic = header.get("magic") or header.get("m")
    if magic and "PROXY" not in str(magic).upper() and "WIRE" not in str(magic).upper():
        print(f"WARNING: Unexpected magic: {magic}")


def load_entries(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    with open(path, "rb") as f:
        header = cbor2.load(f)
        validate_header(header)
        while True:
            try:
                entry = cbor2.load(f)
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                    del entry["enc"]
                entries.append(entry)
            except (EOFError, cbor2.CBORDecodeEOF):
                break
            except cbor2.CBORDecodeError as e:
                print(
                    f"WARNING: stopping at {len(entries)} entries: {e}", file=sys.stderr
                )
                break
    return header, entries


def extract_http_headers(data: bytes) -> dict[str, str]:
    headers = {}
    try:
        text = data.decode("utf-8", errors="replace")
        lines = text.split("\n")
        for line in lines:
            if ": " in line and not line.startswith(
                ("GET ", "POST ", "PUT ", "DELETE ", "PATCH ", "HTTP/")
            ):
                key, _, value = line.partition(": ")
                headers[key.strip().lower()] = value.strip()
    except Exception:
        pass
    return headers


def extract_json_body(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="replace")
        idx = text.find("\r\n\r\n")
        if idx >= 0:
            body_text = text[idx + 4 :]
        else:
            idx = text.find("\n\n")
            if idx >= 0:
                body_text = text[idx + 2 :]
            else:
                body_text = text
        body_text = body_text.strip()
        if body_text.startswith("{"):
            loaded = json.loads(body_text)
            if isinstance(loaded, dict):
                return loaded
    except Exception:
        pass
    return {}


def parse_all_sse_events(data: bytes) -> list[dict[str, Any]]:
    if not data:
        return []
    text = data.decode("utf-8", errors="replace").strip()
    results: list[dict[str, Any]] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            json_str = line[6:].strip()
            if json_str and json_str != "[DONE]":
                try:
                    loaded = json.loads(json_str)
                    if isinstance(loaded, dict):
                        results.append(loaded)
                except json.JSONDecodeError:
                    continue
    return results


if len(sys.argv) > 1:
    cbor_path = sys.argv[1]
else:
    files = sorted(
        (f for f in os.listdir(CBOR_DIR) if f.endswith(".cbor")),
        key=lambda f: os.path.getmtime(os.path.join(CBOR_DIR, f)),
        reverse=True,
    )
    if not files:
        print("No CBOR files found")
        sys.exit(1)
    cbor_path = os.path.join(CBOR_DIR, files[0])

print(f"Analyzing: {cbor_path}")
print(f"File size: {os.path.getsize(cbor_path):,} bytes")

header, entries = load_entries(cbor_path)
print(f"\nTotal entries loaded: {len(entries)}")

direction_counts: dict[int, int] = {}
total_bytes = 0
for e in entries:
    d = e.get("dir", -1)
    direction_counts[d] = direction_counts.get(d, 0) + 1
    total_bytes += len(e.get("data", b""))

dir_names = {
    0: "CLIENT_TO_PROXY",
    1: "PROXY_TO_CLIENT",
    2: "PROXY_TO_BACKEND",
    3: "BACKEND_TO_PROXY",
}
print("Direction counts:")
for d, count in sorted(direction_counts.items()):
    print(f"  {dir_names.get(d, d)}: {count}")
print(f"Total bytes: {total_bytes:,}")

# Find PROXY_TO_BACKEND entries with HTTP request bodies
backend_requests: list[
    tuple[int, dict[str, Any], bytes, dict[str, Any], str, str, str, bool, bool]
] = []
for i, e in enumerate(entries):
    if e.get("dir") != DIRECTION_PROXY_TO_BACKEND:
        continue
    data = e.get("data", b"")
    meta = e.get("meta", {})
    backend_name = meta.get("be", "")
    is_stream_start = meta.get("ss", False)
    method = meta.get("method", "")
    url = meta.get("url", "")
    is_retry = meta.get("rtry", False)
    backend_requests.append(
        (i, e, data, meta, backend_name, method, url, is_stream_start, is_retry)
    )

# Filter for codex backend requests
codex_requests = [
    r
    for r in backend_requests
    if "codex" in r[4].lower() or "/responses" in (r[6] or "").lower()
]
if not codex_requests:
    print(
        "\nNo openai-codex PROXY_TO_BACKEND requests found. Checking all backend requests..."
    )
    codex_requests = backend_requests

print(f"\nTotal backend requests: {len(backend_requests)}")
print(f"Codex/backend requests to analyze: {len(codex_requests)}")

all_payloads: list[dict[str, Any]] = []
conversations: dict[str, list[int]] = {}


def classify_request_shape(payload: dict[str, Any]) -> str:
    has_prev = isinstance(payload.get("previous_response_id"), str) and bool(
        payload.get("previous_response_id")
    )
    has_instr = isinstance(payload.get("instructions"), str) and bool(
        payload.get("instructions")
    )
    tools = payload.get("tools")
    has_tools = isinstance(tools, list) and len(tools) > 0
    if has_prev and not has_instr and not has_tools:
        return "continued_delta"
    if has_prev:
        return "continued_with_bootstrap"
    if has_instr or has_tools:
        return "bootstrap_or_replay"
    return "minimal_unknown"


for idx, (
    i,
    _e,
    data,
    meta,
    backend_name,
    method,
    url,
    is_stream_start,
    is_retry,
) in enumerate(codex_requests):
    payload = extract_json_body(data)
    http_headers = extract_http_headers(data)

    conv_id = http_headers.get("conversation_id", "N/A")
    sess_id = http_headers.get("session_id", "N/A")
    pck = payload.get("prompt_cache_key", "N/A")
    prev_resp_id = payload.get("previous_response_id", "N/A")
    model = payload.get("model", "N/A")
    store = payload.get("store", "N/A")
    stream = payload.get("stream", "N/A")

    input_arr = payload.get("input", [])
    input_count = len(input_arr) if isinstance(input_arr, list) else 0
    input_json_size = len(json.dumps(input_arr)) if input_arr else 0

    tools = payload.get("tools", [])
    tool_count = len(tools) if isinstance(tools, list) else 0
    tools_json_size = len(json.dumps(tools)) if tools else 0

    instructions = payload.get("instructions", "")
    instr_len = len(instructions) if isinstance(instructions, str) else 0

    total_payload_size = len(data)

    reasoning = payload.get("reasoning")
    include = payload.get("include", [])
    req_shape = classify_request_shape(payload)

    req_session = meta.get("asid") or meta.get("sid") or "N/A"

    if conv_id not in conversations:
        conversations[conv_id] = []
    conversations[conv_id].append(idx)

    print(f"\n--- Request #{idx+1} (entry {i}, backend={backend_name}) ---")
    print(f"  URL: {method} {url}")
    print(f"  conversation_id: {conv_id}")
    print(f"  session_id:       {sess_id}")
    print(f"  prompt_cache_key: {pck}")
    print(f"  previous_response_id: {prev_resp_id}")
    print(f"  model: {model}, stream: {stream}, store: {store}")
    print(f"  input[] count: {input_count} items ({input_json_size:,} bytes)")
    print(f"  tools[] count: {tool_count} ({tools_json_size:,} bytes)")
    print(f"  instructions length: {instr_len:,} chars")
    print(f"  reasoning: {reasoning}")
    print(f"  include: {include}")
    print(f"  request shape: {req_shape}")
    print(f"  is_retry: {is_retry}, is_stream_start: {is_stream_start}")
    print(f"  total payload size: {total_payload_size:,} bytes")

    if input_arr:
        type_counts: dict[str, int] = {}
        role_counts: dict[str, int] = {}
        for item in input_arr:
            if isinstance(item, dict):
                t = item.get("type", "<no-type>")
                type_counts[t] = type_counts.get(t, 0) + 1
                r = item.get("role", "")
                if r:
                    role_counts[f"{t}:{r}"] = role_counts.get(f"{t}:{r}", 0) + 1
        print(f"  input type breakdown: {type_counts}")
        if role_counts:
            print(f"  input role breakdown: {role_counts}")

    all_payloads.append(
        {
            "idx": idx,
            "conv_id": conv_id,
            "sess_id": sess_id,
            "pck": pck,
            "prev_resp_id": prev_resp_id,
            "input_count": input_count,
            "input_size": input_json_size,
            "instr_len": instr_len,
            "payload_size": total_payload_size,
            "store": store,
            "model": model,
            "is_retry": is_retry,
            "shape": req_shape,
        }
    )

print("\n\n=== SUMMARY ===")
print(f"Total codex backend requests: {len(codex_requests)}")
print(f"Unique conversation_ids: {len(conversations)}")
for conv_id, reqs in conversations.items():
    pcks = set()
    prev_ids = set()
    retry_count = 0
    for r_idx in reqs:
        p = all_payloads[r_idx]
        pcks.add(str(p["pck"]))
        prev_ids.add(str(p["prev_resp_id"]))
        if p["is_retry"]:
            retry_count += 1
    print(f"\n  conversation_id={conv_id}")
    print(f"    request count: {len(reqs)}, retries: {retry_count}")
    print(f"    prompt_cache_keys used: {pcks}")
    print(f"    previous_response_ids used: {prev_ids}")
    shapes = [all_payloads[r_idx]["shape"] for r_idx in reqs]
    print(f"    shapes: {shapes}")

print("\n\n=== DIAGNOSTIC CHECKS ===")

# Check 1: Is prompt_cache_key stable per conversation?
for conv_id, reqs in conversations.items():
    pcks = {all_payloads[r_idx]["pck"] for r_idx in reqs}
    if len(pcks) > 1:
        print(
            f"[ISSUE] conversation_id={conv_id}: prompt_cache_key CHANGED between requests!"
        )
        print(f"        keys: {pcks}")
    else:
        pck_sample = next(iter(pcks)) if pcks else "N/A"
        print(
            f"[OK]    conversation_id={conv_id}: prompt_cache_key stable ({pck_sample})"
        )

# Check 2: Is previous_response_id ever used?
prev_ids_used = [p["prev_resp_id"] for p in all_payloads if p["prev_resp_id"] != "N/A"]
if prev_ids_used:
    print(f"[OK]    previous_response_id used in {len(prev_ids_used)} requests")
else:
    print(
        "[ISSUE] previous_response_id NEVER used - full conversation replay on every request"
    )

# Check 3: store=false on all requests?
stores = {str(p["store"]) for p in all_payloads}
if stores == {"False"} or stores == {"false"}:
    print("[ISSUE] store=False on ALL requests - no server-side state persistence")
elif stores == {"True"} or stores == {"true"}:
    print("[OK]    store=True - server-side state is persisted")
else:
    print(f"[INFO]  store values: {stores}")

# Check 4: Instructions present and size?
instr_sizes = [p["instr_len"] for p in all_payloads if p["instr_len"] > 0]
if instr_sizes:
    avg_instr = sum(instr_sizes) / len(instr_sizes)
    print(
        f"[INFO]  instructions present in {len(instr_sizes)}/{len(all_payloads)} requests"
    )
    print(
        f"        avg length: {avg_instr:,.0f} chars, max: {max(instr_sizes):,} chars"
    )

# Check 5: Input growth pattern (conversation replay)
for conv_id, reqs in conversations.items():
    if len(reqs) > 1:
        sizes = [all_payloads[r_idx]["payload_size"] for r_idx in reqs]
        input_sizes = [all_payloads[r_idx]["input_size"] for r_idx in reqs]
        input_counts = [all_payloads[r_idx]["input_count"] for r_idx in reqs]
        print(f"\n[INFO]  conversation_id={conv_id}:")
        for j, r_idx in enumerate(reqs):
            p = all_payloads[r_idx]
            print(
                f"        req #{j+1}: input_count={p['input_count']}, input_size={p['input_size']:,}B, payload_size={p['payload_size']:,}B, pck={p['pck'][:40] if p['pck'] != 'N/A' else 'N/A'}"
            )
        strictly_increasing = all(
            sizes[i] < sizes[i + 1] for i in range(len(sizes) - 1)
        )
        non_decreasing = all(sizes[i] <= sizes[i + 1] for i in range(len(sizes) - 1))
        if strictly_increasing:
            print(
                "        [CRITICAL] Payload sizes STRICTLY INCREASING - full conversation replay!"
            )
        elif non_decreasing:
            print(
                "        [WARN] Payload sizes non-decreasing - likely full conversation replay"
            )

# Check 6: Delta-style continued requests
continued_delta = [p for p in all_payloads if p["shape"] == "continued_delta"]
continued_with_bootstrap = [
    p for p in all_payloads if p["shape"] == "continued_with_bootstrap"
]
print(
    f"\n[INFO]  request shapes: bootstrap/replay={sum(1 for p in all_payloads if p['shape'] == 'bootstrap_or_replay')}, "
    f"continued_delta={len(continued_delta)}, continued_with_bootstrap={len(continued_with_bootstrap)}"
)
if continued_with_bootstrap:
    print(
        "[WARN]  continued requests still carrying bootstrap fields were detected; inspect those turns."
    )
elif continued_delta:
    print("[OK]    continued delta-style requests detected without bootstrap fields.")

# Check 7: Are there duplicate-sized payloads (retries)?
for conv_id, reqs in conversations.items():
    unique_sizes = {all_payloads[r_idx]["payload_size"] for r_idx in reqs}
    if len(reqs) > len(unique_sizes) + 2:
        print(
            f"\n[WARN]  conversation_id={conv_id}: {len(reqs)} requests but only {len(unique_sizes)} unique payload sizes - possible retries"
        )
