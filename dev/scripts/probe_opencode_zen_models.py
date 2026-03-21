"""One-off helper: fetch OpenCode Zen /models and print normalized IDs (no secrets)."""

from __future__ import annotations

import json
import sys

import httpx

# Mirror llm_proxy_oauth_connectors.opencode_zen.OpencodeZenConnector._normalize_model_name
DEFAULT_ENDPOINT = "https://opencode.ai/zen/v1"


def normalize_model_name(model_name: str) -> str:
    exact_mappings = {
        "glm-4.6": "z-ai/glm-4.6",
        "qwen3-coder": "qwen/qwen3-coder",
        "kimi-k2": "moonshotai/kimi-k2-0905",
        "kimi-k2-thinking": "moonshotai/kimi-k2-thinking",
        "grok-code": "x-ai/grok-code-fast-1",
        "big-pickle": "stealth/big-pickle",
        "alpha-gd4": "stealth/alpha-gd4",
    }
    if model_name in exact_mappings:
        return exact_mappings[model_name]
    if "/" in model_name:
        return model_name
    if model_name.startswith("claude"):
        return f"anthropic/{model_name}"
    if model_name.startswith(("gpt", "o1-")):
        return f"openai/{model_name}"
    if model_name.startswith("gemini"):
        return f"google/{model_name}"
    if model_name.startswith("minimax"):
        return f"minimax/{model_name}"
    if model_name.startswith("glm"):
        return f"z-ai/{model_name}"
    if model_name.startswith("kimi"):
        return f"moonshotai/{model_name}"
    if model_name.startswith("qwen"):
        return f"qwen/{model_name}"
    return model_name


def main() -> int:
    url = f"{DEFAULT_ENDPOINT}/models"
    r = httpx.get(url, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        print("Unexpected payload", file=sys.stderr)
        return 1
    raw_ids = [m["id"] for m in rows if isinstance(m, dict) and "id" in m]
    normalized = [normalize_model_name(i) for i in raw_ids]
    out = {
        "fetched_at_utc": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
        "source_url": url,
        "raw_model_ids": raw_ids,
        "normalized_vendor_slash_ids": normalized,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
