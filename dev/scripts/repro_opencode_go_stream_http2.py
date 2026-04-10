from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx


def _ensure_repo_root_on_path() -> None:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "src" / "connectors" / "openai.py").is_file():
            root = str(ancestor)
            if root not in sys.path:
                sys.path.insert(0, root)
            return
    raise RuntimeError("Could not locate repo root containing src/connectors/openai.py")


_ensure_repo_root_on_path()

from src.connectors.opencode_go import OpencodeGoBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "opencode-go:kimi-k2.5"


@dataclass(frozen=True)
class ProbeResult:
    http2: bool
    iteration: int
    ok: bool
    chunks: int
    elapsed_ms: float
    error_type: str | None
    error: str | None


def _build_config() -> AppConfig:
    config = MagicMock(spec=AppConfig)
    config.streaming_yield_interval = 0.0
    config.backends = MagicMock()
    return config


def _build_request(model: str, prompt: str, max_tokens: int) -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content=prompt)],
        max_tokens=max_tokens,
        stream=True,
    )


async def _run_once(
    client: httpx.AsyncClient,
    backend: OpencodeGoBackend,
    *,
    http2: bool,
    iteration: int,
    model: str,
    prompt: str,
    max_tokens: int,
) -> ProbeResult:
    _ = client
    started = time.perf_counter()
    chunks = 0
    try:
        async for _chunk in backend.stream_completion(
            _build_request(model, prompt, max_tokens)
        ):
            chunks += 1
            if chunks >= 6:
                break
        return ProbeResult(
            http2=http2,
            iteration=iteration,
            ok=True,
            chunks=chunks,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error_type=None,
            error=None,
        )
    except Exception as exc:
        return ProbeResult(
            http2=http2,
            iteration=iteration,
            ok=False,
            chunks=chunks,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error_type=type(exc).__name__,
            error=str(exc),
        )


async def _run_series(
    *,
    http2: bool,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    iterations: int,
) -> list[ProbeResult]:
    async with httpx.AsyncClient(
        http2=http2,
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
        trust_env=False,
    ) as client:
        backend = OpencodeGoBackend(
            client=client,
            config=_build_config(),
            translation_service=TranslationService(),
        )
        await backend.initialize(
            api_key=api_key,
            api_base_url=base_url,
            openai_api_base_url=base_url,
            anthropic_api_base_url=base_url,
            key_name="opencode-go",
            model_protocol_overrides={},
        )
        backend.disable_health_check()
        try:
            results: list[ProbeResult] = []
            for iteration in range(1, iterations + 1):
                results.append(
                    await _run_once(
                        client,
                        backend,
                        http2=http2,
                        iteration=iteration,
                        model=model,
                        prompt=prompt,
                        max_tokens=max_tokens,
                    )
                )
            return results
        finally:
            await backend.close()


async def amain() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=os.environ.get("OPENCODE_GO_API_KEY"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default="Reply with exactly: ok")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--iterations", type=int, default=16)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("OPENCODE_GO_API_KEY is required")

    results: list[dict[str, Any]] = []
    for http2 in (True, False):
        series = await _run_series(
            http2=http2,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            prompt=args.prompt,
            max_tokens=args.max_tokens,
            iterations=args.iterations,
        )
        results.extend(asdict(result) for result in series)

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
