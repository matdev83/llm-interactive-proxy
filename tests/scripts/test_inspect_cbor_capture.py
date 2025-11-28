import json
import subprocess
import sys
from pathlib import Path

import cbor2

SCRIPT_PATH = Path("scripts/inspect_cbor_capture.py")


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
    header = {"session_id": "test_session", "created_at": 1234567890.0, "metadata": {}}

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
