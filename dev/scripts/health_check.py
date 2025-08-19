import sys
import time
import httpx


def main(timeout_seconds: int = 20) -> int:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            r = httpx.get("http://127.0.0.1:8000/internal/health", timeout=2)
            print(r.text)
            return 0
        except Exception as e:
            print("waiting", e)
            time.sleep(1)
    print("NO_HEALTH")
    return 2


if __name__ == "__main__":
    sys.exit(main())


