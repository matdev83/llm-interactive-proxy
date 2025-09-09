from __future__ import annotations

import os
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient, Limits, Timeout


def _should_run_real() -> bool:
    return os.getenv("RUN_REAL_ZAI", "0") in ("1", "true", "TRUE", "yes") and bool(
        os.getenv("ZAI_API_KEY")
    )


pytestmark = pytest.mark.skipif(
    not _should_run_real(),
    reason="Set RUN_REAL_ZAI=1 and provide ZAI_API_KEY to run real tests",
)


@pytest.mark.anyio
@pytest.mark.no_global_mock
async def test_zai_real_non_stream_endpoints() -> None:
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
    assert zai_key, "ZAI_API_KEY must be set for real tests"

    # Unique prompt per run
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    uniq = abs(hash(now)) % 100000
    prompt = (
        f"Write a Python function named 'smoke_{uniq}' that returns {uniq}+1. "
        f"Timestamp: {now}"
    )

    # Build app with real backends
    cfg = AppConfig()
    cfg.auth.disable_auth = True
    cfg.backends.default_backend = "zai-coding-plan"
    cfg.backends.zai_coding_plan = BackendConfig(api_key=[zai_key])

    builder = ApplicationTestBuilder()
    builder.add_stage(CoreServicesStage())
    builder.add_stage(InfrastructureStage())
    builder.add_stage(RealBackendTestStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())
    app = await builder.build(cfg)

    # Use in-memory ASGI transport
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
        # OpenAI endpoint
        r1 = await client.post(
            "/v1/chat/completions",
            json={
                "model": "zai-coding-plan:claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
            },
        )
        assert r1.status_code == 200, r1.text
        j1 = r1.json()
        text1 = j1.get("choices", [{}])[0].get("message", {}).get("content", "")
        assert str(uniq) in str(text1)

        # Anthropic endpoint
        r2 = await client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
            },
        )
        assert r2.status_code == 200, r2.text
        j2 = r2.json()
        text2 = j2.get("content", [{}])[0].get("text", "")
        assert str(uniq) in str(text2)


@pytest.mark.anyio
@pytest.mark.no_global_mock
async def test_zai_real_stream_endpoints() -> None:
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
    assert zai_key, "ZAI_API_KEY must be set for real tests"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    uniq = abs(hash(now)) % 100000
    prompt = (
        f"Stream: define 'stream_{uniq}' that returns {uniq}*2. " f"Timestamp: {now}"
    )

    cfg = AppConfig()
    cfg.auth.disable_auth = True
    cfg.backends.default_backend = "zai-coding-plan"
    cfg.backends.zai_coding_plan = BackendConfig(api_key=[zai_key])

    builder = ApplicationTestBuilder()
    builder.add_stage(CoreServicesStage())
    builder.add_stage(InfrastructureStage())
    builder.add_stage(RealBackendTestStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())
    app = await builder.build(cfg)

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
        # OpenAI streaming
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "zai-coding-plan:claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 128,
                "stream": True,
            },
        ) as s1:
            assert s1.status_code == 200
            count1 = 0
            async for line in s1.aiter_lines():
                if line:
                    count1 += 1
                if count1 >= 3:
                    break
            assert count1 >= 1

        # Anthropic streaming
        async with client.stream(
            "POST",
            "/anthropic/v1/messages",
            json={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 128,
                "stream": True,
            },
        ) as s2:
            assert s2.status_code == 200
            count2 = 0
            async for line in s2.aiter_lines():
                if line:
                    count2 += 1
                if count2 >= 3:
                    break
            assert count2 >= 1
