import os
import subprocess
import sys
from time import sleep


def start_server(detach: bool = True) -> int:
    """Start the application server as a detached process and return its PID.

    The script assumes it's run with the project's venv python so it uses
    sys.executable to spawn the server module.
    """
    out_path = os.path.join(os.getcwd(), "dev", "server_run.out.log")
    err_path = os.path.join(os.getcwd(), "dev", "server_run.err.log")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    cmd = [sys.executable, "-u", "-m", "src.core.cli", "--disable-auth"]

    out_f = open(out_path, "ab")
    err_f = open(err_path, "ab")

    creationflags = 0
    # On Windows, use DETACHED_PROCESS to avoid inheriting console
    if sys.platform.startswith("win") and detach:
        creationflags = 0x00000008  # CREATE_NO_WINDOW / DETACHED_PROCESS

    proc = subprocess.Popen(
        cmd,
        stdout=out_f,
        stderr=err_f,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )

    # Give the server a small amount of time to start
    sleep(1.5)

    print(proc.pid)
    return proc.pid


if __name__ == "__main__":
    start_server()


