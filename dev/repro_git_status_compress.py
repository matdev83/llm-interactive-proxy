from src.core.domain.configuration.dynamic_compression_config import (
    CompressionMarkerConfig,
    DynamicCompressionConfig,
)
from tests.unit.core.services.test_tool_output_compression_service import (
    _build_service_with_default_registry,
    _build_tool_messages,
)


async def main() -> None:
    service = _build_service_with_default_registry()
    lines = ["## develop...origin/develop"]
    lines += [f" M services/long_name_module_{i:02d}.py" for i in range(20)]
    content = "\n".join(lines) + "\n"
    messages = _build_tool_messages("git status", content)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=DynamicCompressionConfig().rules,
    )
    result = await service.compress_messages(messages=messages, config=cfg)
    r = result.records[0]
    print("decision", r.decision_reason if hasattr(r, "decision_reason") else r)
    print("rule", getattr(r, "selected_rule_name", None))
    print("applied", r.applied)
    print("content head", str(result.messages[1].content)[:200])


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
