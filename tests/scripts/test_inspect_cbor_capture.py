import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import cbor2
import pytest
import src.core.wire_capture.inspection as inspector

SCRIPT_PATH = Path("scripts/inspect_cbor_capture.py")


def _write_capture_file(capture_file: Path, entries: list[dict[str, object]]) -> None:
    """Write a minimal V2 CBOR capture file for end-to-end inspector tests."""
    header = {
        "magic": "LLMPROXY-CAPTURE-V2",
        "version": 2,
        "session_id": "fixture-session",
        "created_at": 1234567890.0,
        "metadata": {},
    }

    with open(capture_file, "wb") as f:
        cbor2.dump(header, f)
        for entry in entries:
            cbor2.dump(entry, f)


def test_script_exists():
    """Verify that the inspect_cbor_capture.py script exists."""
    assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"


def test_script_help():
    """Verify that the script runs and shows help."""
    cmd = [sys.executable, str(SCRIPT_PATH), "--help"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Inspect CBOR wire capture files" in result.stdout


def test_script_analysis(tmp_path):
    """Verify basic analysis functionality with a generated capture file."""
    capture_file = tmp_path / "test_capture.cbor"

    # Create a minimal capture file
    header = {
        "magic": "LLMPROXY-CAPTURE-V2",
        "version": 2,
        "session_id": "test_session",
        "created_at": 1234567890.0,
        "metadata": {},
    }

    with open(capture_file, "wb") as f:
        cbor2.dump(header, f)

        # Request
        cbor2.dump(
            {
                "seq": 0,
                "dir": 0,  # CLIENT_TO_PROXY
                "ts": 1000.0,
                "data": json.dumps({"model": "test-model", "messages": []}).encode(
                    "utf-8"
                ),
            },
            f,
        )

        # Response (Tool Call)
        cbor2.dump(
            {
                "seq": 1,
                "dir": 3,  # BACKEND_TO_PROXY
                "ts": 1000.5,
                "data": b'data: {"choices": [{"delta": {"tool_calls": [{"function": {"name": "test_tool"}}]}}]}\n\n',
                "meta": {"be": "test-backend"},
            },
            f,
        )

        # Response (Done)
        cbor2.dump(
            {
                "seq": 2,
                "dir": 3,  # BACKEND_TO_PROXY
                "ts": 1001.0,
                "data": b"data: [DONE]\n\n",
                "meta": {"be": "test-backend"},
            },
            f,
        )

    # Run analysis
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        str(capture_file),
        "--analyze",
        "--verbose",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    assert result.returncode == 0
    output = result.stdout

    # Check for expected output
    assert "CAPTURE FILE SUMMARY" in output
    assert "REQUEST/RESPONSE ANALYSIS" in output
    assert "Model: test-model" in output
    assert "test_tool" in output  # Tool name verification
    assert "Timing: TTFT=0.500s" in output  # Timing verification


def test_load_capture_file_rejects_unsupported_version(tmp_path):
    """The inspector should reject old capture versions before reading entries."""
    capture_file = tmp_path / "v1_capture.cbor"

    header = {
        "magic": "LLMPROXY-CAPTURE-V2",
        "version": 1,
        "session_id": "test_session",
        "created_at": 1234567890.0,
        "metadata": {},
    }

    with open(capture_file, "wb") as f:
        cbor2.dump(header, f)

    with pytest.raises(ValueError, match="Unsupported capture file version: 1"):
        inspector.load_capture_file(capture_file)


def test_detect_issues_correlates_by_request_id_before_session_ids():
    """Regression: avoid false missing response when asid/bsid differ across legs."""

    entries = [
        {
            "seq": 10,
            "dir": 0,  # C->P
            "ts": 1000.0,
            "meta": {"rid": "req-1", "asid": "a-session"},
            "data": b"{}",
        },
        {
            "seq": 11,
            "dir": 2,  # P->B
            "ts": 1000.1,
            "meta": {
                "rid": "req-1",
                "asid": "a-session",
                "bsid": "b-session",
                "be": "gemini-oauth-auto",
            },
            "data": b"{}",
        },
        {
            "seq": 12,
            "dir": 3,  # B->P
            "ts": 1000.2,
            "meta": {
                "rid": "req-1",
                "asid": "a-session",
                "be": "gemini-oauth-auto",
            },
            "data": b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
        },
    ]

    issues = inspector.detect_issues(entries)
    assert not [i for i in issues if i["type"] == "missing_response"]


def test_detect_issues_falls_back_to_asid_when_bsid_missing_on_response():
    """Regression: sid fallback should check both asid and bsid."""

    entries = [
        {
            "seq": 20,
            "dir": 0,  # C->P
            "ts": 2000.0,
            "meta": {"rid": "req-2", "asid": "a-session"},
            "data": b"{}",
        },
        {
            "seq": 21,
            "dir": 2,  # P->B
            "ts": 2000.1,
            "meta": {
                "rid": "req-2",
                "asid": "a-session",
                "bsid": "b-session",
                "be": "gemini-oauth-auto",
            },
            "data": b"{}",
        },
        {
            "seq": 22,
            "dir": 3,  # B->P
            "ts": 2000.2,
            "meta": {"asid": "a-session", "be": "gemini-oauth-auto"},
            "data": b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
        },
    ]

    issues = inspector.detect_issues(entries)
    assert not [i for i in issues if i["type"] == "missing_response"]


def test_print_summary_uses_v2_http_status_metadata(capsys):
    """Status summary should read compact V2 HTTP metadata keys."""

    header = {
        "magic": "LLMPROXY-CAPTURE-V2",
        "version": 2,
        "session_id": "test-session",
        "created_at": 1234567890.0,
        "metadata": {},
    }
    entries = [
        {"seq": 0, "dir": 2, "ts": 1000.0, "data": b"{}", "meta": {"be": "openai"}},
        {
            "seq": 1,
            "dir": 3,
            "ts": 1000.1,
            "data": b"",
            "meta": {"be": "openai", "http_status": 429},
        },
        {
            "seq": 2,
            "dir": 3,
            "ts": 1000.2,
            "data": b"",
            "meta": {"be": "anthropic", "sc": 500},
        },
    ]

    inspector.print_summary(header, entries, show_status_summary=True)
    output = capsys.readouterr().out

    assert "HTTP Status Summary (from metadata):" in output
    assert "429: 1 (50.0%)" in output
    assert "500: 1 (50.0%)" in output
    assert "openai: 429 1/1 (100.0%)" in output


def test_print_entries_verbose_expands_compact_v2_metadata(capsys):
    """Verbose entry output should expand compact metadata keys to readable names."""

    entries = [
        {
            "seq": 7,
            "dir": 3,
            "ts": 1000.0,
            "data": b"chunk",
            "meta": {
                "be": "openai",
                "asid": "a-session-123456",
                "bsid": "b-session-654321",
                "rid": "req-123",
                "ss": True,
                "wire_schema": "v2",
                "transport": "http",
                "event": "frame",
                "http_status": 200,
                "ttfb": 125.0,
            },
        }
    ]

    inspector.print_entries(entries, max_entries=10, verbose=True)
    output = capsys.readouterr().out

    assert "stream_start" in output
    assert "request_id: req-123" in output
    assert "wire_schema: v2" in output
    assert "transport: http" in output
    assert "protocol_event: frame" in output
    assert "http_status_code: 200" in output
    assert "ttfb_ms: 125.0" in output


def test_analyze_request_response_pairs_uses_v2_stream_timing_metadata():
    """Analysis timing should prefer V2 stream timing metadata over marker timestamps."""

    entries = [
        {
            "seq": 0,
            "dir": 0,
            "ts": 1000.0,
            "data": json.dumps({"model": "gpt-4o-mini"}).encode("utf-8"),
            "meta": {"rid": "req-1"},
        },
        {
            "seq": 1,
            "dir": 3,
            "ts": 1000.01,
            "data": b"",
            "meta": {"be": "openai", "rid": "req-1", "ss": True},
        },
        {
            "seq": 2,
            "dir": 3,
            "ts": 1000.15,
            "data": b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n',
            "meta": {"be": "openai", "rid": "req-1", "ttfb": 150.0},
        },
        {
            "seq": 3,
            "dir": 3,
            "ts": 1001.0,
            "data": b"",
            "meta": {"be": "openai", "rid": "req-1", "se": True},
        },
        {
            "seq": 4,
            "dir": 0,
            "ts": 1002.0,
            "data": b"{}",
            "meta": {"rid": "req-2"},
        },
    ]

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        inspector.analyze_request_response_pairs(entries)
    output = stdout.getvalue()

    assert "Timing: TTFT=0.150s, Duration=1.000s" in output


def test_analyze_request_response_pairs_handles_interleaved_requests_by_request_id():
    """Interleaved requests should not steal each other's backend chunks."""

    entries = [
        {
            "seq": 0,
            "dir": 0,
            "ts": 1000.0,
            "data": json.dumps({"model": "kiro-model"}).encode("utf-8"),
            "meta": {"rid": "req-kiro"},
        },
        {
            "seq": 1,
            "dir": 0,
            "ts": 1000.1,
            "data": json.dumps({"model": "zai-model"}).encode("utf-8"),
            "meta": {"rid": "req-zai"},
        },
        {
            "seq": 2,
            "dir": 3,
            "ts": 1000.2,
            "data": b'data: {"model":"kiro-backend","choices":[{"delta":{"content":"title"}}]}\n\n',
            "meta": {"rid": "req-kiro", "be": "kiro-oauth-auto", "ttfb": 200.0},
        },
        {
            "seq": 3,
            "dir": 3,
            "ts": 1000.3,
            "data": b'{"error":{"message":"Insufficient balance"}}',
            "meta": {"rid": "req-zai", "be": "zai-coding-plan", "ttfb": 200.0},
        },
    ]

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        inspector.analyze_request_response_pairs(entries)
    output = stdout.getvalue()
    request_2_section = output.split("--- REQUEST #2 ---", 1)[1]

    assert "--- REQUEST #1 ---" in output
    assert "Model: kiro-model" in output
    assert "Backend models: {'kiro-backend'}" in output
    assert "--- REQUEST #2 ---" in output
    assert "Model: zai-model" in output
    assert "Backend Error: Insufficient balance" in output
    assert "Backend models: {'kiro-backend'}" not in request_2_section


def test_analyze_streaming_handles_interleaved_requests_by_request_id():
    """Streaming analysis should correlate chunks by request_id, not next request boundary."""

    entries = [
        {
            "seq": 0,
            "dir": 2,
            "ts": 1000.0,
            "data": b"req-1",
            "meta": {"rid": "req-1", "be": "backend-a"},
        },
        {
            "seq": 1,
            "dir": 2,
            "ts": 1000.1,
            "data": b"req-2",
            "meta": {"rid": "req-2", "be": "backend-b"},
        },
        {
            "seq": 2,
            "dir": 3,
            "ts": 1000.2,
            "data": b"chunk-a",
            "meta": {"rid": "req-1", "be": "backend-a", "ttfb": 200.0},
        },
        {
            "seq": 3,
            "dir": 3,
            "ts": 1000.3,
            "data": b"chunk-b",
            "meta": {"rid": "req-2", "be": "backend-b", "ttfb": 200.0},
        },
        {
            "seq": 4,
            "dir": 3,
            "ts": 1000.4,
            "data": b"",
            "meta": {"rid": "req-1", "be": "backend-a", "se": True},
        },
    ]

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        inspector.analyze_streaming(entries)
    output = stdout.getvalue()

    assert "--- Stream #1 (Entry [0]) ---" in output
    assert "Time to First Token: 0.200s" in output
    assert "Chunks: 2" not in output
    assert "Chunks: 1" in output
    assert (
        "No backend response chunks"
        not in output.split("--- Stream #1 (Entry [0]) ---", 1)[1].split(
            "--- Stream #2", 1
        )[0]
    )


def test_load_capture_file_decompresses_zlib_payload(tmp_path):
    """Compressed V2 payloads should be transparently decompressed on load."""
    capture_file = tmp_path / "compressed_capture.cbor"

    with open(capture_file, "wb") as f:
        cbor2.dump(
            {
                "magic": "LLMPROXY-CAPTURE-V2",
                "version": 2,
                "session_id": "compressed-session",
                "created_at": 1234567890.0,
                "metadata": {},
            },
            f,
        )
        cbor2.dump(
            {
                "seq": 1,
                "dir": 3,
                "ts": 1000.0,
                "data": b"x\x9c\xcbH\xcd\xc9\xc9W(\xcf/\xcaI\x01\x00\x1a\x0b\x04]",
                "enc": "zlib",
                "meta": {"be": "openai"},
            },
            f,
        )

    _header, entries = inspector.load_capture_file(capture_file)

    assert len(entries) == 1
    assert entries[0]["data"] == b"hello world"
    assert "enc" not in entries[0]


def test_export_to_json_normalizes_metadata_and_honors_backend_filter(capsys):
    """JSON export should include readable V2 metadata and backend filtering."""

    header = {
        "magic": "LLMPROXY-CAPTURE-V2",
        "version": 2,
        "session_id": "test-session",
        "created_at": 1234567890.0,
        "metadata": {},
    }
    entries = [
        {
            "seq": 1,
            "dir": 3,
            "ts": 1000.0,
            "data": b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n',
            "meta": {"be": "openai", "rid": "req-1", "http_status": 200},
        },
        {
            "seq": 2,
            "dir": 3,
            "ts": 1000.1,
            "data": b'{"error": {"message": "skip me"}}',
            "meta": {"be": "anthropic", "rid": "req-2", "http_status": 500},
        },
    ]

    inspector.export_to_json(header, entries, output_file=None, backend_filter="openai")
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert payload["header"]["session_id"] == "test-session"
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["metadata"]["backend"] == "openai"
    assert payload["entries"][0]["metadata"]["request_id"] == "req-1"
    assert payload["entries"][0]["metadata"]["http_status_code"] == 200
    assert payload["entries"][0]["parsed"]["choices"][0]["delta"]["content"] == "hi"


def test_print_timeline_marks_slow_gaps_and_respects_backend_filter(capsys):
    """Timeline output should show backend filtering and highlight large gaps."""

    entries = [
        {"seq": 1, "dir": 2, "ts": 1000.0, "data": b"a", "meta": {"be": "openai"}},
        {"seq": 2, "dir": 3, "ts": 1000.5, "data": b"b", "meta": {"be": "openai"}},
        {"seq": 3, "dir": 3, "ts": 1012.0, "data": b"c", "meta": {"be": "openai"}},
        {
            "seq": 4,
            "dir": 3,
            "ts": 1012.1,
            "data": b"ignored",
            "meta": {"be": "anthropic"},
        },
    ]

    inspector.print_timeline(entries, backend_filter="openai")
    output = capsys.readouterr().out

    assert "TIMELINE VIEW" in output
    assert "(Filtered to backend: openai)" in output
    assert "[1]" in output and "[2]" in output and "[3]" in output
    assert "[4]" not in output
    assert "!!! +11.5s SLOW !!!" in output


def test_track_request_handles_interleaved_flows_by_request_id():
    """Tracked request flow should not stop at an unrelated interleaved client request."""

    entries = [
        {
            "seq": 10,
            "dir": 2,
            "ts": 1000.0,
            "data": b"backend-req-1",
            "meta": {"rid": "req-1", "be": "openai"},
        },
        {
            "seq": 11,
            "dir": 2,
            "ts": 1000.1,
            "data": b"backend-req-2",
            "meta": {"rid": "req-2", "be": "openai"},
        },
        {
            "seq": 12,
            "dir": 3,
            "ts": 1000.2,
            "data": b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n',
            "meta": {"rid": "req-1", "be": "openai"},
        },
        {
            "seq": 13,
            "dir": 1,
            "ts": 1000.3,
            "data": b"data: hello\n\n",
            "meta": {"rid": "req-1"},
        },
    ]

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        inspector.track_request(entries, request_num=1, backend_filter="openai")
    output = stdout.getvalue()

    assert "REQUEST FLOW TRACKING - Request #1" in output
    assert "[START] [10] C->P" not in output
    assert "[START] [10] P->B  Forwarded to backend" in output
    assert "[B->P] [12] Content chunk" in output
    assert "[P->C] [13] Forwarded to client" in output


def test_cli_analyze_golden_realistic_v2_capture(tmp_path):
    """CLI analyze output should stay stable for a realistic V2 HTTP stream."""
    capture_file = tmp_path / "golden_analyze.cbor"
    _write_capture_file(
        capture_file,
        [
            {
                "seq": 0,
                "dir": 0,
                "ts": 1000.0,
                "data": json.dumps({"model": "kiro-oauth-auto:claude-opus"}).encode(
                    "utf-8"
                ),
                "meta": {"rid": "req-1", "asid": "a-session-1"},
            },
            {
                "seq": 1,
                "dir": 2,
                "ts": 1000.1,
                "data": b"POST /v1/chat/completions HTTP/1.1",
                "meta": {
                    "rid": "req-1",
                    "asid": "a-session-1",
                    "be": "kiro-oauth-auto",
                },
            },
            {
                "seq": 2,
                "dir": 3,
                "ts": 1000.2,
                "data": b"",
                "meta": {
                    "rid": "req-1",
                    "asid": "a-session-1",
                    "be": "kiro-oauth-auto",
                    "ss": True,
                    "http_status": 200,
                },
            },
            {
                "seq": 3,
                "dir": 3,
                "ts": 1000.35,
                "data": b'data: {"model":"claude-opus-4.6","choices":[{"delta":{"tool_calls":[{"function":{"name":"bash"}}]}}]}\n\n',
                "meta": {
                    "rid": "req-1",
                    "asid": "a-session-1",
                    "be": "kiro-oauth-auto",
                    "ttfb": 350.0,
                    "http_status": 200,
                },
            },
            {
                "seq": 4,
                "dir": 3,
                "ts": 1001.0,
                "data": b"",
                "meta": {
                    "rid": "req-1",
                    "asid": "a-session-1",
                    "be": "kiro-oauth-auto",
                    "se": True,
                    "http_status": 200,
                },
            },
            {
                "seq": 5,
                "dir": 1,
                "ts": 1001.1,
                "data": b"data: done\n\n",
                "meta": {"rid": "req-1", "asid": "a-session-1"},
            },
        ],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(capture_file), "--analyze"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "REQUEST/RESPONSE ANALYSIS" in result.stdout
    assert "Model: kiro-oauth-auto:claude-opus" in result.stdout
    assert "Timing: TTFT=0.350s, Duration=1.000s" in result.stdout
    assert "Backend models: {'claude-opus-4.6'}" in result.stdout
    assert "1 tool_calls (bash)" in result.stdout


def test_cli_timeline_golden_realistic_v2_capture(tmp_path):
    """CLI timeline output should remain readable for realistic inter-entry gaps."""
    capture_file = tmp_path / "golden_timeline.cbor"
    _write_capture_file(
        capture_file,
        [
            {
                "seq": 10,
                "dir": 0,
                "ts": 1000.0,
                "data": b"req",
                "meta": {"asid": "a-session-abcdef", "be": "client"},
            },
            {
                "seq": 11,
                "dir": 2,
                "ts": 1000.2,
                "data": b"backend request",
                "meta": {"asid": "a-session-abcdef", "be": "openai"},
            },
            {
                "seq": 12,
                "dir": 3,
                "ts": 1012.6,
                "data": b"backend response",
                "meta": {"asid": "a-session-abcdef", "be": "openai"},
            },
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(capture_file),
            "--timeline",
            "--backend",
            "openai",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "TIMELINE VIEW" in result.stdout
    assert "(Filtered to backend: openai)" in result.stdout
    assert "[11]  P->B" in result.stdout
    assert "[12]  B->P" in result.stdout
    assert "!!! +12.4s SLOW !!!" in result.stdout


def test_cli_track_request_golden_realistic_interleaved_capture(tmp_path):
    """CLI request tracking should follow one request through interleaved backend traffic."""
    capture_file = tmp_path / "golden_track_request.cbor"
    _write_capture_file(
        capture_file,
        [
            {
                "seq": 20,
                "dir": 2,
                "ts": 1000.0,
                "data": b"backend request 1",
                "meta": {"rid": "req-1", "be": "openai"},
            },
            {
                "seq": 21,
                "dir": 2,
                "ts": 1000.1,
                "data": b"backend request 2",
                "meta": {"rid": "req-2", "be": "openai"},
            },
            {
                "seq": 22,
                "dir": 3,
                "ts": 1000.3,
                "data": b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n',
                "meta": {"rid": "req-1", "be": "openai"},
            },
            {
                "seq": 23,
                "dir": 1,
                "ts": 1000.4,
                "data": b"data: hello\n\n",
                "meta": {"rid": "req-1"},
            },
            {
                "seq": 24,
                "dir": 3,
                "ts": 1000.5,
                "data": b'{"error": {"message": "rate limited"}}',
                "meta": {"rid": "req-2", "be": "openai"},
            },
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(capture_file),
            "--track-request",
            "1",
            "--backend",
            "openai",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "REQUEST FLOW TRACKING - Request #1" in result.stdout
    assert "[START] [20] P->B  Forwarded to backend" in result.stdout
    assert "[B->P] [22] Content chunk" in result.stdout
    assert "[P->C] [23] Forwarded to client" in result.stdout
    assert "[24]" not in result.stdout
