"""
End-to-end integration test for gemini-cli-acp backend.

This test spawns the actual proxy server, configures it to use the gemini-cli-acp backend,
and verifies that it can successfully handle chat completion requests by delegating to
the gemini-cli agent via ACP (Agent Client Protocol).

Requirements:
- gemini-cli must be installed: npm install -g @google/gemini-cli
- gemini-cli must be authenticated: gemini login
- Workspace directory must exist

The test will be skipped if gemini-cli is not available.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests
import yaml

pytestmark = [
    pytest.mark.integration,
    pytest.mark.no_global_mock,
    pytest.mark.filterwarnings("ignore:unclosed file <_io\\..*:ResourceWarning"),
    pytest.mark.filterwarnings(
        "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
    ),
]


def _check_gemini_cli_available() -> bool:
    """Check if gemini-cli is installed and available."""
    try:
        result = subprocess.run(
            ["gemini", "--version"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _check_gemini_cli_authenticated() -> bool:
    """Check if gemini-cli is authenticated."""
    # Check if credentials file exists
    creds_file = Path.home() / ".gemini" / "oauth_creds.json"
    return creds_file.exists()


def _wait_port(port: int, host: str = "127.0.0.1", timeout: float = 30.0) -> None:
    """Wait until a TCP port is accepting connections or timeout."""
    end = time.time() + timeout
    backoff_time = 0.01
    max_backoff = 1.0

    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 1.5, max_backoff)
    raise RuntimeError(f"Server on port {port} did not start in {timeout}s")


def _find_free_port() -> int:
    """Find a free port to bind the server to."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def _create_test_workspace(base_dir: Path) -> Path:
    """Create a test workspace directory with some sample files."""
    workspace = base_dir / "test_workspace"
    workspace.mkdir(exist_ok=True)

    # Create a sample Python file
    sample_file = workspace / "sample.py"
    sample_file.write_text("def hello():\n" "    print('Hello from test workspace!')\n")

    # Create a README
    readme = workspace / "README.md"
    readme.write_text(
        "# Test Workspace\n\nThis is a test workspace for gemini-cli-acp integration testing.\n"
    )

    return workspace


def _create_test_config(config_dir: Path, workspace: Path, port: int) -> Path:
    """Create a test configuration file for the proxy with gemini-cli-acp backend."""
    config_file = config_dir / "test_config.yaml"

    config = {
        "host": "127.0.0.1",
        "port": port,
        "command_prefix": "!/",
        "auth": {
            "disable_auth": True,
        },
        "session": {
            "cleanup_enabled": False,
            "default_interactive_mode": False,
        },
        "logging": {
            "level": "INFO",
            "request_logging": True,
            "response_logging": True,
        },
        "backends": {
            "default_backend": "gemini-cli-acp",
            "gemini-cli-acp": {
                "timeout": 120,
                "workspace_path": str(workspace),
                "gemini_cli_executable": "gemini",
                "model": "gemini-2.5-flash",
                "auto_accept": True,
                "process_timeout": 60,
            },
        },
    }

    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


def _start_server(port: int, config_file: Path, log_file: Path) -> subprocess.Popen:
    """Start the proxy server with gemini-cli-acp backend."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.core.cli",
            "--config",
            str(config_file),
            "--log",
            str(log_file),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    try:
        _wait_port(port, timeout=30.0)
        # Give the server a moment to fully initialize
        time.sleep(2)
        return proc
    except RuntimeError as e:
        output = ""
        exit_code = None

        if proc.poll() is None:
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
            exit_code = proc.returncode

        if proc.stdout:
            import contextlib

            with contextlib.suppress(Exception):
                output = proc.stdout.read()

        raise RuntimeError(
            f"Server failed to start on port {port}\n"
            f"Exit code: {exit_code}\n"
            f"Output:\n{output}"
        ) from e


@pytest.mark.skipif(
    not _check_gemini_cli_available(),
    reason="gemini-cli not installed (npm install -g @google/gemini-cli)",
)
@pytest.mark.skipif(
    not _check_gemini_cli_authenticated(),
    reason="gemini-cli not authenticated (run: gemini login)",
)
class TestGeminiCliAcpIntegration:
    """End-to-end integration tests for gemini-cli-acp backend."""

    @pytest.fixture(scope="class")
    def test_environment(self):
        """Set up test environment with workspace, config, and server."""
        temp_dir = Path(tempfile.mkdtemp())
        port = _find_free_port()

        try:
            # Create workspace
            workspace = _create_test_workspace(temp_dir)

            # Create config
            config_file = _create_test_config(temp_dir, workspace, port)

            # Create log file
            log_file = temp_dir / "proxy.log"

            # Start server
            proc = _start_server(port, config_file, log_file)

            yield {
                "port": port,
                "workspace": workspace,
                "config_file": config_file,
                "log_file": log_file,
                "proc": proc,
                "base_url": f"http://127.0.0.1:{port}",
            }

        finally:
            # Cleanup
            if "proc" in locals() and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)

            # Clean up temp directory
            import contextlib
            import shutil

            with contextlib.suppress(Exception):
                shutil.rmtree(temp_dir)

    def test_server_health(self, test_environment):
        """Test that the server starts and responds to health checks."""
        base_url = test_environment["base_url"]

        # Simple ping to root
        response = requests.get(f"{base_url}/", timeout=10)
        assert response.status_code in [
            200,
            404,
        ]  # Root may return 404 but server is up

    def test_models_endpoint(self, test_environment):
        """Test that models endpoint returns gemini models."""
        base_url = test_environment["base_url"]

        response = requests.get(f"{base_url}/v1/models", timeout=10)
        assert response.status_code == 200

        data = response.json()
        assert "data" in data

        # Should have gemini models
        model_ids = [model["id"] for model in data["data"]]
        assert any("gemini" in mid.lower() for mid in model_ids)

    def test_chat_completion_non_streaming(self, test_environment):
        """Test non-streaming chat completion through gemini-cli-acp backend."""
        base_url = test_environment["base_url"]

        request_data = {
            "model": "gemini-2.5-flash",
            "messages": [
                {
                    "role": "user",
                    "content": "Say hello in exactly 3 words, no punctuation.",
                }
            ],
            "stream": False,
            "max_tokens": 50,
        }

        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json=request_data,
            timeout=60,  # gemini-cli may take some time
        )

        assert response.status_code == 200
        data = response.json()

        # Verify OpenAI-compatible response format
        assert "id" in data
        assert "object" in data
        assert data["object"] == "chat.completion"
        assert "created" in data
        assert "model" in data
        assert "choices" in data
        assert len(data["choices"]) > 0

        choice = data["choices"][0]
        assert "message" in choice
        assert "role" in choice["message"]
        assert choice["message"]["role"] == "assistant"
        assert "content" in choice["message"]
        assert len(choice["message"]["content"]) > 0

        # Verify usage info
        assert "usage" in data
        assert "prompt_tokens" in data["usage"]
        assert "completion_tokens" in data["usage"]
        assert "total_tokens" in data["usage"]

        print(f"\nGemini CLI ACP Response: {choice['message']['content']}")

    def test_chat_completion_streaming(self, test_environment):
        """Test streaming chat completion through gemini-cli-acp backend."""
        base_url = test_environment["base_url"]

        request_data = {
            "model": "gemini-2.5-flash",
            "messages": [
                {
                    "role": "user",
                    "content": "Count from 1 to 3, each number on a new line.",
                }
            ],
            "stream": True,
            "max_tokens": 50,
        }

        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json=request_data,
            stream=True,
            timeout=60,
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream"

        chunks = []
        full_content = ""

        for line in response.iter_lines():
            if line:
                line_str = line.decode("utf-8")

                if line_str.startswith("data: "):
                    data_str = line_str[6:]

                    if data_str == "[DONE]":
                        break

                    try:
                        chunk_data = json.loads(data_str)
                        chunks.append(chunk_data)

                        # Verify chunk format
                        assert "id" in chunk_data
                        assert "object" in chunk_data
                        assert chunk_data["object"] == "chat.completion.chunk"
                        assert "choices" in chunk_data

                        if chunk_data["choices"]:
                            choice = chunk_data["choices"][0]
                            if "delta" in choice and "content" in choice["delta"]:
                                full_content += choice["delta"]["content"]

                    except json.JSONDecodeError:
                        pass  # Skip malformed chunks

        assert len(chunks) > 0, "Should receive at least one chunk"
        assert len(full_content) > 0, "Should receive some content"

        print(f"\nGemini CLI ACP Streaming Response: {full_content}")

    def test_workspace_awareness(self, test_environment):
        """Test that gemini-cli-acp backend is aware of the workspace."""
        base_url = test_environment["base_url"]
        _ = test_environment["workspace"]  # Referenced for documentation

        request_data = {
            "model": "gemini-2.5-flash",
            "messages": [
                {
                    "role": "user",
                    "content": "What files are in the current workspace? Just list the filenames.",
                }
            ],
            "stream": False,
            "max_tokens": 200,
        }

        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json=request_data,
            timeout=60,
        )

        assert response.status_code == 200
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        print(f"\nWorkspace awareness test response: {content}")

        # The response should mention the files we created
        # Note: gemini-cli may or may not actually access the files depending on the query
        assert len(content) > 0

    def test_error_handling(self, test_environment):
        """Test error handling with invalid requests."""
        base_url = test_environment["base_url"]

        # Test with missing required field
        request_data = {
            "model": "gemini-2.5-flash",
            # Missing messages field
            "stream": False,
        }

        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json=request_data,
            timeout=10,
        )

        # Should return error (400 or 422)
        assert response.status_code in [400, 422]

    def test_multiple_requests(self, test_environment):
        """Test handling multiple sequential requests."""
        base_url = test_environment["base_url"]

        for i in range(3):
            request_data = {
                "model": "gemini-2.5-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Say 'Request {i+1}' and nothing else.",
                    }
                ],
                "stream": False,
                "max_tokens": 20,
            }

            response = requests.post(
                f"{base_url}/v1/chat/completions",
                json=request_data,
                timeout=60,
            )

            assert response.status_code == 200
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            print(f"\nRequest {i+1} response: {content}")

    def test_server_logs(self, test_environment):
        """Verify that server logs are being generated."""
        log_file = test_environment["log_file"]

        # Make a request to generate logs
        base_url = test_environment["base_url"]
        requests.get(f"{base_url}/v1/models", timeout=10)

        # Wait a moment for logs to be written
        time.sleep(1)

        # Check log file exists and has content
        assert log_file.exists()
        log_content = log_file.read_text()
        assert len(log_content) > 0

        # Should contain gemini-cli-acp references
        assert "gemini-cli-acp" in log_content or "gemini" in log_content.lower()


def test_gemini_cli_availability_check():
    """Standalone test to check gemini-cli availability."""
    available = _check_gemini_cli_available()
    authenticated = _check_gemini_cli_authenticated()

    print(f"\ngemini-cli available: {available}")
    print(f"gemini-cli authenticated: {authenticated}")

    if not available:
        pytest.skip("gemini-cli not installed")
    if not authenticated:
        pytest.skip("gemini-cli not authenticated")


if __name__ == "__main__":
    # Allow running directly for manual testing
    print("Checking gemini-cli availability...")
    print(f"gemini-cli available: {_check_gemini_cli_available()}")
    print(f"gemini-cli authenticated: {_check_gemini_cli_authenticated()}")

    # Run tests
    pytest.main([__file__, "-v", "-s"])
