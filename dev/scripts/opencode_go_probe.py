"""Live probes for OpenCode Go API shapes (auth, headers, model ids).

Maps case name prefixes to diagnostic hypotheses (see --help).

Writes optional NDJSON session log for agent/debug workflows (no secrets).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
_SESSION_LOG = Path(__file__).resolve().parents[2] / "debug-6933c2.log"


@dataclass(frozen=True)
class ProbeCase:
    name: str
    hypothesis_id: str
    endpoint: str
    headers: dict[str, str]
    payload: dict[str, Any]


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "x-api-key"}:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def _preview_body(text: str, limit: int = 280) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _hypothesis_for_openai_auth(_auth_name: str) -> str:
    return "A"


def _hypothesis_for_anthropic_auth(_auth_name: str) -> str:
    return "B"


def _append_session_ndjson(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
) -> None:
    # region agent log
    payload = {
        "sessionId": "6933c2",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _SESSION_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # endregion


def build_cases(api_key: str, base_url: str) -> list[ProbeCase]:
    """Assemble probe matrix: auth x models x optional gateway headers."""
    base = base_url.rstrip("/")
    auth_variants: dict[str, dict[str, str]] = {
        "bearer": {"Authorization": f"Bearer {api_key}"},
        "x-api-key": {"x-api-key": api_key},
        "both": {
            "Authorization": f"Bearer {api_key}",
            "x-api-key": api_key,
        },
        "raw_key_in_authorization": {"Authorization": api_key},
        "bearer_lowercase": {"authorization": f"Bearer {api_key}"},
    }

    anthropic_models = [
        "minimax-m2.7",
        "minimax-m2.5",
        "opencode-go/minimax-m2.7",
    ]
    openai_models = [
        "kimi-k2.5",
        "glm-5.1",
        "opencode-go/kimi-k2.5",
    ]

    cases: list[ProbeCase] = []

    for auth_name, auth_headers in auth_variants.items():
        hid = _hypothesis_for_anthropic_auth(auth_name)
        for model in anthropic_models:
            cases.append(
                ProbeCase(
                    name=f"anthropic/{auth_name}/{model}",
                    hypothesis_id=hid,
                    endpoint=f"{base}/messages",
                    headers={
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                        **auth_headers,
                    },
                    payload={
                        "model": model,
                        "max_tokens": 16,
                        "stream": False,
                        "messages": [{"role": "user", "content": "Say OK."}],
                    },
                )
            )

    for auth_name, auth_headers in auth_variants.items():
        hid = _hypothesis_for_openai_auth(auth_name)
        for model in openai_models:
            cases.append(
                ProbeCase(
                    name=f"openai/{auth_name}/{model}",
                    hypothesis_id=hid,
                    endpoint=f"{base}/chat/completions",
                    headers={
                        "content-type": "application/json",
                        **auth_headers,
                    },
                    payload={
                        "model": model,
                        "max_tokens": 16,
                        "stream": False,
                        "messages": [{"role": "user", "content": "Say OK."}],
                    },
                )
            )

    # H-C: optional headers some gateways require (no secret values)
    opencode_ua = "opencode/1.2.26 (llm-interactive-proxy; opencode_go_probe)"
    extras: dict[str, dict[str, str]] = {
        "referer_opencode": {"HTTP-Referer": "https://opencode.ai/"},
        "referer_plus_title": {
            "HTTP-Referer": "https://opencode.ai/",
            "X-Title": "opencode",
        },
        "accept_json": {"Accept": "application/json"},
        "ua_opencode": {"User-Agent": opencode_ua},
        "ua_referer_combo": {
            "User-Agent": opencode_ua,
            "HTTP-Referer": "https://opencode.ai/",
        },
    }
    for extra_name, extra_h in extras.items():
        cases.append(
            ProbeCase(
                name=f"openai/extra_{extra_name}/kimi-k2.5",
                hypothesis_id="C",
                endpoint=f"{base}/chat/completions",
                headers={
                    "content-type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    **extra_h,
                },
                payload={
                    "model": "kimi-k2.5",
                    "max_tokens": 16,
                    "stream": False,
                    "messages": [{"role": "user", "content": "Say OK."}],
                },
            )
        )
        cases.append(
            ProbeCase(
                name=f"anthropic/extra_{extra_name}/minimax-m2.7",
                hypothesis_id="C",
                endpoint=f"{base}/messages",
                headers={
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                    "x-api-key": api_key,
                    **extra_h,
                },
                payload={
                    "model": "minimax-m2.7",
                    "max_tokens": 16,
                    "stream": False,
                    "messages": [{"role": "user", "content": "Say OK."}],
                },
            )
        )

    # H-D: alternate Anthropic version header (some proxies differ)
    cases.append(
        ProbeCase(
            name="anthropic/x-api-key_anthropic_version_beta/minimax-m2.7",
            hypothesis_id="D",
            endpoint=f"{base}/messages",
            headers={
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "messages-2023-12-15",
                "content-type": "application/json",
                "x-api-key": api_key,
            },
            payload={
                "model": "minimax-m2.7",
                "max_tokens": 16,
                "stream": False,
                "messages": [{"role": "user", "content": "Say OK."}],
            },
        )
    )

    return cases


def _print_summary(results: list[dict[str, Any]]) -> None:
    ok = [r for r in results if isinstance(r.get("status"), int) and r["status"] < 300]
    print("\n--- summary (2xx = success) ---", flush=True)
    print(f"total={len(results)} ok_2xx={len(ok)}", flush=True)
    for r in results:
        st = r.get("status")
        mark = "OK " if isinstance(st, int) and st < 300 else "ERR"
        print(f"  [{mark}] {st}\t{r.get('name')}", flush=True)
    if ok:
        print("\nSuccessful case names (use these shapes in the proxy):", flush=True)
        for r in ok:
            print(f"  - {r.get('name')}", flush=True)


async def run_case(client: httpx.AsyncClient, case: ProbeCase) -> dict[str, Any]:
    try:
        response = await client.post(
            case.endpoint, headers=case.headers, json=case.payload
        )
        body = response.text
        try:
            parsed: Any = response.json()
        except Exception:
            parsed = None
        return {
            "name": case.name,
            "hypothesis_id": case.hypothesis_id,
            "status": response.status_code,
            "headers": _redact_headers(case.headers),
            "payload_model": case.payload.get("model"),
            "body_preview": _preview_body(body),
            "json": parsed,
        }
    except Exception as exc:
        return {
            "name": case.name,
            "hypothesis_id": case.hypothesis_id,
            "status": None,
            "headers": _redact_headers(case.headers),
            "payload_model": case.payload.get("model"),
            "body_preview": f"request failed: {exc}",
            "json": None,
        }


async def amain() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe OpenCode Go HTTP API. Hypotheses: "
            "H-A openai/* auth shapes; H-B anthropic/* auth; "
            "H-C Referer/UA/Accept; H-D anthropic-version/beta."
        )
    )
    parser.add_argument("--api-key", default=os.environ.get("OPENCODE_GO_API_KEY"))
    parser.add_argument(
        "--base-url", default=os.environ.get("OPENCODE_GO_API_BASE_URL")
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--session-log",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Append NDJSON lines to debug-6933c2.log at repo root (no secrets).",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only JSON array (no summary).",
    )
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key:
        raise SystemExit("OPENCODE_GO_API_KEY env var or --api-key is required")

    base_url = (args.base_url or DEFAULT_BASE_URL).strip()
    cases = build_cases(api_key, base_url)
    async with httpx.AsyncClient(timeout=args.timeout, follow_redirects=True) as client:
        results: list[dict[str, Any]] = []
        for case in cases:
            row = await run_case(client, case)
            results.append(row)
            if args.session_log:
                _append_session_ndjson(
                    hypothesis_id=case.hypothesis_id,
                    location="dev/scripts/opencode_go_probe.py",
                    message="probe_case_result",
                    data={
                        "case": row.get("name"),
                        "status": row.get("status"),
                        "payload_model": row.get("payload_model"),
                        "body_preview": row.get("body_preview"),
                    },
                )

    if args.session_log:
        _append_session_ndjson(
            hypothesis_id="SUMMARY",
            location="dev/scripts/opencode_go_probe.py",
            message="probe_run_complete",
            data={
                "base_url": base_url,
                "case_count": len(results),
                "ok_2xx": sum(
                    1
                    for r in results
                    if isinstance(r.get("status"), int) and r["status"] < 300
                ),
            },
        )

    print(json.dumps(results, indent=2))
    if not args.json_only:
        _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
