import json
from pathlib import Path


def _redact_token(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "<missing>"
    # Show only length + a tiny prefix for correlation without leaking secrets.
    prefix = value[:6]
    return f"<len={len(value)} prefix={prefix!r}>"


def main() -> int:
    creds_path = Path.home() / ".qwen" / "oauth_creds.json"
    if not creds_path.exists():
        print(f"Missing: {creds_path}")
        return 1

    data = json.loads(creds_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("Invalid credentials: expected JSON object")
        return 2

    print(f"Path: {creds_path}")
    print(f"Keys: {sorted([str(k) for k in data.keys()])}")
    print(f"token_type: {data.get('token_type')!r}")
    print(f"expiry_date: {data.get('expiry_date')!r}")
    print(f"resource_url: {data.get('resource_url')!r}")
    print(f"access_token: {_redact_token(data.get('access_token'))}")
    print(f"refresh_token: {_redact_token(data.get('refresh_token'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
