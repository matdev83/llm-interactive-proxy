import json

import requests


def main() -> int:
    base_url = "http://127.0.0.1:8000"
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": "qwen-oauth:qwen/coder-model",
        "messages": [
            {"role": "user", "content": "Hi there. What this project is all about?"}
        ],
        "stream": True,
        "max_tokens": 200,
    }

    with requests.post(
        url,
        json=payload,
        headers={"Authorization": "Bearer test-key"},
        stream=True,
        timeout=60,
    ) as resp:
        print("status", resp.status_code)
        printed = 0
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace")
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    print("[DONE]")
                    break
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    parsed = None
                if parsed is not None:
                    # Print just the delta keys for quick inspection.
                    choices = (
                        parsed.get("choices") if isinstance(parsed, dict) else None
                    )
                    delta = None
                    if (
                        isinstance(choices, list)
                        and choices
                        and isinstance(choices[0], dict)
                    ):
                        d = choices[0].get("delta")
                        if isinstance(d, dict):
                            delta = d
                    if isinstance(delta, dict):
                        print(
                            "delta_keys",
                            sorted([k for k, v in delta.items() if v is not None]),
                        )
                print(line[:250])
                printed += 1
                if printed >= 12:
                    break
            else:
                print(line[:250])
                printed += 1
                if printed >= 12:
                    break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
