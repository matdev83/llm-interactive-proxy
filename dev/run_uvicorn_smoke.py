import subprocess
import sys
import time

import httpx


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "src.core.cli",
        "--disable-auth",
        "--host",
        "127.0.0.1",
        "--port",
        "8001",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Wait for server to start
        time.sleep(2)
        url = "http://127.0.0.1:8001/models"
        try:
            r = httpx.get(url, timeout=5.0)
            print("STATUS", r.status_code)
            print("CONTENT-TYPE", r.headers.get("content-type"))
            print(r.text[:1000])
            success = r.status_code == 200
        except Exception as e:
            print("ERROR during request:", e)
            success = False
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
