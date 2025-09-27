import os
import random
import socket
import subprocess
import sys
import time

import pytest
import requests

pytestmark = [
    pytest.mark.integration,
    pytest.mark.no_global_mock,
    # Suppress occasional unclosed file warning from pytest internals on Windows
    pytest.mark.filterwarnings("ignore:unclosed file <_io\\..*:ResourceWarning"),
]


def _wait_port(port: int, host: str = "127.0.0.1", timeout: float = 60.0) -> None:
    """Wait until a TCP port is accepting connections or timeout.

    Args:
        port: Port to probe
        host: Host to connect to
        timeout: Max seconds to wait
    Raises:
        RuntimeError: If the port did not become ready in time
    """
    end = time.time() + timeout
    # Use exponential backoff for more efficient waiting
    backoff_time = 0.01  # Start with 10ms
    max_backoff = 1.0  # Max 1 second between attempts

    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            # Use exponential backoff instead of fixed 0.1s sleep
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 1.5, max_backoff)
    raise RuntimeError("server did not start")


def _start_server(port: int, log_file: str) -> subprocess.Popen:
    """Start the proxy via CLI in a subprocess so logging is configured."""
    env = os.environ.copy()
    # Ensure at least one backend is functional for smoke test
    env["OPENROUTER_API_KEY_1"] = "test-key-for-smoke-test"
    env["COMMAND_PREFIX"] = "!/"
    # Optimize startup with faster logging and reduced checks
    env["PYTHONUNBUFFERED"] = "1"
    env["LOG_LEVEL"] = "WARNING"  # Reduce logging overhead
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
            "--log-level",  # Add log level to reduce startup overhead
            "WARNING",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    try:
        _wait_port(port, timeout=15.0)  # Reduce timeout from 30s to 15s
        return proc
    except RuntimeError as e:
        # If port wait failed, capture process output for debugging
        output = ""
        exit_code = None

        # Check if process is still running
        if proc.poll() is None:
            # Process is still running, terminate it
            try:
                proc.terminate()
                try:
                    exit_code = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    exit_code = proc.wait(timeout=2)
            except Exception:
                pass
        else:
            # Process already exited
            exit_code = proc.returncode

        # Get output
        if proc.stdout is not None:
            try:
                output = proc.stdout.read() or ""
            except Exception:
                output = ""

        # Also try to read the log file
        log_content = ""
        try:
            with open(log_file) as f:
                log_content = f.read()
        except Exception:
            pass

        raise RuntimeError(
            f"{e}\nProcess exit code: {exit_code}\nProcess output:\n{output}\nLog file content:\n{log_content}"
        )


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


def _pick_port(low: int = 1024, high: int = 65535) -> int:
    # Use a more predictable port range to avoid conflicts
    # Test ports in the ephemeral range but avoid commonly used ports
    return random.randint(8000, 9000)


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
        # Simple, dependency-free endpoint with reduced timeout
        r = requests.get(f"http://127.0.0.1:{port}/docs", timeout=3)
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
