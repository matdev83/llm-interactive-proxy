import json
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import cbor2
import pytest

SCRIPT_PATH = Path("scripts/inspect_cbor_capture.py")


def _load_inspector_module():
    """Load inspect_cbor_capture.py as a module for direct unit testing."""
    spec = spec_from_file_location("inspect_cbor_capture", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    inspector = _load_inspector_module()
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
    inspector = _load_inspector_module()

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
    inspector = _load_inspector_module()

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
