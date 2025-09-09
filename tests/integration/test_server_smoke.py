import os
import random
import socket
import subprocess
import sys
import time

import pytest
import requests

pytestmark = [pytest.mark.integration]


def _wait_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> None:
    """Wait until a TCP port is accepting connections or timeout.

    Args:
        port: Port to probe
        host: Host to connect to
        timeout: Max seconds to wait
    Raises:
        RuntimeError: If the port did not become ready in time
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def _start_server(port: int, log_file: str) -> subprocess.Popen:
    """Start the proxy via CLI in a subprocess so logging is configured."""
    env = os.environ.copy()
    # Run the real CLI so it configures logging/file handlers
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.core.cli",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--disable-auth",
            "--log",
            log_file,
            "--allow-admin",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    _wait_port(port)
    return proc


def _stop_server(proc: subprocess.Popen) -> str:
    """Terminate the server and return combined stdout/stderr for inspection."""
    out = ""
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    finally:
        if proc.stdout is not None:
            try:
                out = proc.stdout.read() or ""
            except Exception:
                out = ""
    return out


def _pick_port(low: int = 8400, high: int = 8800) -> int:
    return random.randint(low, high)


def _has_bad_output(s: str) -> bool:
    # Keep this conservative to avoid false positives from warnings
    needles = ["Traceback (most recent call last)", "Unhandled exception", "FATAL"]
    return any(n in s for n in needles)


def _log_has_critical_errors(path: str) -> bool:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = f.read()
            # Allow WARNINGs; fail on ERROR/CRITICAL (line starts or anywhere)
            if data.startswith(("ERROR", "CRITICAL")):
                return True
            return ("\nERROR" in data) or ("\nCRITICAL" in data)
    except FileNotFoundError:
        # If the log file was not created, treat as failure to be strict
        return True


def test_server_starts_and_logs_cleanly(tmp_path: "os.PathLike[str]") -> None:
    """Smoke test: start server, hit a simple endpoint, and verify no crashes.

    - Starts uvicorn in background with our ASGI factory.
    - Waits briefly for readiness, then GETs /docs.
    - Ensures no obvious crashes/tracebacks on STDOUT/STDERR.
    - Ensures application log file has no ERROR/CRITICAL entries.
    """
    port = _pick_port()
    log_file = str(tmp_path / "server.log")
    proc = _start_server(port, log_file)
    try:
        # Simple, dependency-free endpoint
        r = requests.get(f"http://127.0.0.1:{port}/docs", timeout=5)
        assert r.status_code == 200
    finally:
        output = _stop_server(proc)

    # Check process output for crashes/tracebacks
    assert not _has_bad_output(
        output
    ), f"Server output indicates crash/traceback:\n{output}"

    # Check app log for critical errors
    assert not _log_has_critical_errors(
        log_file
    ), f"Application log contains errors: {log_file}\n\nOutput:\n{output}"
