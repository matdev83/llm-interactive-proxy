#!/usr/bin/env python3
"""
ZAI E2E Smoke Test
- Builds the app with real backends
- Sends unique prompt to /v1/chat/completions and /anthropic/v1/messages (non-stream)
- Then attempts streaming on both endpoints and prints first few chunks
- Falls back to direct HTTP call to ZAI with KiloCode headers
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def call_via_proxy_openai(app, prompt: str) -> bool:
    from httpx import ASGITransport, AsyncClient, Limits, Timeout

    print("Calling proxy /v1/chat/completions ...")
    transport = ASGITransport(app=app)
    try:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=True,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    except ImportError:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=False,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    async with client as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "zai-coding-plan:claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
            },
        )
        print(f"Proxy status: {resp.status_code}")
        if resp.status_code != 200:
            print(resp.text[:500])
            return False
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            content = str(data)[:400]
        print("Proxy (OpenAI) response (first 400 chars):")
        print(str(content)[:400])
        return True


async def stream_via_proxy_openai(app, prompt: str) -> bool:
    from httpx import ASGITransport, AsyncClient, Limits, Timeout

    print("Streaming via /v1/chat/completions ...")
    transport = ASGITransport(app=app)
    try:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=True,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    except ImportError:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=False,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    async with client as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "zai-coding-plan:claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 128,
                "stream": True,
            },
        ) as resp:
            print(f"OpenAI stream status: {resp.status_code}")
            if resp.status_code != 200:
                print(await resp.aread())
                return False
            shown = 0
            async for line in resp.aiter_lines():
                if line:
                    print(line[:200])
                    shown += 1
                if shown >= 8:
                    break
    return True


async def call_via_proxy_anthropic(app, prompt: str) -> bool:
    from httpx import ASGITransport, AsyncClient, Limits, Timeout

    print("Calling proxy /anthropic/v1/messages ...")
    transport = ASGITransport(app=app)
    try:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=True,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    except ImportError:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=False,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    async with client as client:
        resp = await client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        print(f"Proxy (anthropic) status: {resp.status_code}")
        print("Proxy (Anthropic) raw JSON:")
        print(resp.text[:1000])
        return resp.status_code == 200


async def stream_via_proxy_anthropic(app, prompt: str) -> bool:
    from httpx import ASGITransport, AsyncClient, Limits, Timeout

    print("Streaming via /anthropic/v1/messages ...")
    transport = ASGITransport(app=app)
    try:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=True,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    except ImportError:
        client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            http2=False,
            timeout=Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    async with client as client:
        async with client.stream(
            "POST",
            "/anthropic/v1/messages",
            json={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 128,
                "stream": True,
            },
        ) as resp:
            print(f"Anthropic stream status: {resp.status_code}")
            if resp.status_code != 200:
                print(await resp.aread())
                return False
            shown = 0
            async for line in resp.aiter_lines():
                if line:
                    print(line[:200])
                    shown += 1
                if shown >= 8:
                    break
    return True


async def call_via_proxy() -> bool:
    from src.core.app.stages import (
        CommandStage,
        ControllerStage,
        CoreServicesStage,
        InfrastructureStage,
        ProcessorStage,
    )
    from src.core.app.stages.test_stages import RealBackendTestStage
    from src.core.app.test_builder import ApplicationTestBuilder
    from src.core.config.app_config import AppConfig, BackendConfig

    zai_key = os.environ.get("ZAI_API_KEY")
    if not zai_key:
        print("ZAI_API_KEY not set in environment.")
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    uniq = abs(hash(now)) % 100000
    prompt = (
        f"Write a Python function named 'smoke_{uniq}' that returns {uniq}+1. "
        f"Timestamp: {now}"
    )

    # Build app
    cfg = AppConfig()
    cfg.auth.disable_auth = True
    cfg.backends.default_backend = "zai-coding-plan"
    try:
        cfg.backends.zai_coding_plan = BackendConfig(api_key=[zai_key])
    except Exception:
        pass

    builder = ApplicationTestBuilder()
    builder.add_stage(CoreServicesStage())
    builder.add_stage(InfrastructureStage())
    builder.add_stage(RealBackendTestStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())
    app = await builder.build(cfg)

    ok_openai = await call_via_proxy_openai(app, prompt)
    ok_anth = await call_via_proxy_anthropic(app, prompt)

    # Attempt streaming after non-stream
    await stream_via_proxy_openai(app, prompt)
    await stream_via_proxy_anthropic(app, prompt)

    return ok_openai and ok_anth


async def call_direct_zai() -> bool:
    import httpx

    zai_key = os.environ.get("ZAI_API_KEY")
    if not zai_key:
        print("ZAI_API_KEY not set in environment.")
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    uniq = abs(hash(now)) % 100000
    prompt = (
        f"Direct test: define 'direct_{uniq}' that returns {uniq}*2. "
        f"Timestamp: {now}"
    )

    headers = {
        "Authorization": f"Bearer {zai_key}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Kilo-Code/4.84.0",
        "HTTP-Referer": "https://kilocode.ai",
        "X-Title": "Kilo Code",
        "X-KiloCode-Version": "4.84.0",
    }
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 256,
        "messages": [{"role": "user", "content": prompt}],
    }

    print("Calling ZAI directly ...")
    try:
        client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    except ImportError:
        client = httpx.AsyncClient(
            http2=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
    async with client as client:
        try:
            r = await client.post(
                "https://api.z.ai/api/anthropic/v1/messages",
                json=payload,
                headers=headers,
            )
        except Exception as e:
            print(f"Direct call error: {e}")
            return False
        print(f"Direct status: {r.status_code}")
        print("Direct raw JSON (first 600):")
        print(r.text[:600])
        return r.status_code == 200


async def main() -> int:
    ok = await call_via_proxy()
    if ok:
        return 0
    print("Proxy attempt(s) failed or non-contextual. Falling back to direct ZAI call.")
    ok2 = await call_direct_zai()
    return 0 if ok2 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
