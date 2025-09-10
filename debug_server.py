#!/usr/bin/env python3
"""Debug script to test server startup"""

import logging
import os
import socket
import subprocess
import sys
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_server_startup():
    """Test server startup with detailed debugging"""

    # Set environment
    env = os.environ.copy()
    env["OPENROUTER_API_KEY_1"] = "test-key-for-smoke-test"

    # Start server
    cmd = [
        sys.executable,
        "-m",
        "src.core.cli",
        "--host",
        "127.0.0.1",
        "--port",
        "8002",
        "--disable-auth",
        "--log",
        "debug_server.log",
        "--allow-admin",
    ]

    logger.info(f"Starting server with command: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Wait a bit and check if process is still running
    time.sleep(2)

    if proc.poll() is not None:
        logger.error(f"Process exited with code: {proc.returncode}")
        stdout, stderr = proc.communicate()
        logger.info(f"STDOUT:\n{stdout}")
        logger.error(f"STDERR:\n{stderr}")
        return False

    # Try to connect to port
    for _ in range(50):  # 5 seconds total
        try:
            with socket.create_connection(("127.0.0.1", 8002), timeout=1):
                logger.info("Server is responding!")
                proc.terminate()
                return True
        except OSError:
            time.sleep(0.1)

    logger.error("Server did not start listening on port")

    # Get final output
    try:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        logger.info(f"Final STDOUT:\n{stdout}")
        logger.error(f"Final STDERR:\n{stderr}")
    except subprocess.TimeoutExpired:
        proc.kill()

    return False


if __name__ == "__main__":
    success = test_server_startup()
    logger.info(f"Test {'PASSED' if success else 'FAILED'}")
