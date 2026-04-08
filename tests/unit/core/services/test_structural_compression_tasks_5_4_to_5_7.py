"""Tasks 5.4-5.7: JSON/NDJSON, XML safeguards, log dedupe, sensitive projection."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from typing import Any

import pytest
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContentType, ToolOutputContext
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.structural_compression_strategies import (
    JsonNdjsonStructuralStrategy,
    LogLineDedupeStrategy,
    SensitiveFieldProjectionStrategy,
    XmlMachineSafeguardStrategy,
)


def _ctx(
    content: str,
    *,
    content_type: ToolOutputContentType = ToolOutputContentType.JSON,
    command_signature: str | None = "curl",
    command_prefix: str | None = None,
    explicit: bool = False,
) -> ToolOutputContext:
    base = ToolOutputContext.for_text(
        tool_name="shell",
        tool_category="command_execution",
        content=content,
        command_signature=command_signature,
        command_prefix=command_prefix,
    )
    return base.model_copy(
        update={
            "content_type": content_type,
            "has_explicit_format": explicit,
            "is_machine_parseable": content_type
            in (
                ToolOutputContentType.JSON,
                ToolOutputContentType.NDJSON,
                ToolOutputContentType.XML,
            ),
        }
    )


def test_json_structural_summarizes_nested_and_truncates_strings() -> None:
    long_url = "https://example.com/" + "x" * 80
    payload: dict[str, Any] = {
        "a": 1,
        "b": {"c": 2, "d": 3, "e": 4},
        "items": list(range(30)),
        "u": long_url,
    }
    raw = json.dumps(payload, separators=(",", ":"))
    strategy = JsonNdjsonStructuralStrategy(
        max_depth=4,
        max_keys_per_object=3,
        max_array_elements=4,
        string_max_len=20,
        min_bytes=16,
    )
    out = strategy.compress(
        raw,
        context=_ctx(raw, content_type=ToolOutputContentType.JSON),
        level=CompressionLevel.CONSERVATIVE,
    )
    parsed = json.loads(out)
    assert "b" in parsed
    assert isinstance(parsed["items"], list)
    assert len(parsed["items"]) < len(payload["items"])
    tail = parsed["items"][-1]
    assert isinstance(tail, dict) and "_more_elements" in tail
    u_val = str(parsed.get("u", ""))
    assert "url[" in u_val or len(u_val) < len(long_url)


def test_json_structural_omits_primitive_literals_and_keeps_type_markers() -> None:
    payload = {
        "active": True,
        "attempt": 7,
        "ratio": 3.14159,
        "optional": None,
        "secret": "top-secret-value",
        "url": "https://example.com/resource",
        "date": "2026-04-08",
        "long_text": "x" * 64,
        "nested": {"token": "abc123", "count": 987654321},
        "items": [{"id": 123456789, "ok": False}],
    }
    raw = json.dumps(payload, separators=(",", ":"))
    strategy = JsonNdjsonStructuralStrategy(
        max_depth=6,
        max_keys_per_object=30,
        max_array_elements=4,
        string_max_len=16,
        min_bytes=1,
    )
    out = strategy.compress(
        raw,
        context=_ctx(raw, content_type=ToolOutputContentType.JSON),
        level=CompressionLevel.BALANCED,
    )
    parsed = json.loads(out)

    assert parsed["active"] == "bool"
    assert parsed["attempt"] == "int"
    assert parsed["ratio"] == "float"
    assert parsed["optional"] == "null"
    assert parsed["secret"] == "string"
    assert parsed["url"] == "url[28]"
    assert parsed["date"] == "date"
    assert parsed["long_text"] == "string[64]"
    assert parsed["nested"]["token"] == "string"
    assert parsed["nested"]["count"] == "int"
    assert parsed["items"][0]["id"] == "int"
    assert parsed["items"][0]["ok"] == "bool"

    assert "top-secret-value" not in out
    assert "abc123" not in out
    assert "987654321" not in out
    assert "3.14159" not in out


def test_json_structural_fail_open_on_invalid_json() -> None:
    strategy = JsonNdjsonStructuralStrategy(min_bytes=1)
    bad = "{not json"
    assert (
        strategy.compress(
            bad,
            context=_ctx(bad, content_type=ToolOutputContentType.JSON),
            level=CompressionLevel.BALANCED,
        )
        == bad
    )


def test_json_structural_skips_when_explicit_machine_format_requested() -> None:
    strategy = JsonNdjsonStructuralStrategy(min_bytes=1)
    raw = json.dumps({"x": list(range(50))})
    out = strategy.compress(
        raw,
        context=_ctx(raw, content_type=ToolOutputContentType.JSON, explicit=True),
        level=CompressionLevel.BALANCED,
    )
    assert out == raw


def test_ndjson_structural_shape_counts_deterministic() -> None:
    lines = [
        json.dumps({"a": 1, "b": 2}, separators=(",", ":")),
        json.dumps({"a": 3, "b": 4}, separators=(",", ":")),
        json.dumps({"z": 9}, separators=(",", ":")),
    ]
    raw = "\n".join(lines) + "\n"
    strategy = JsonNdjsonStructuralStrategy(
        max_depth=4,
        max_keys_per_object=20,
        max_array_elements=8,
        string_max_len=40,
        min_bytes=10,
    )
    out = strategy.compress(
        raw,
        context=_ctx(raw, content_type=ToolOutputContentType.NDJSON),
        level=CompressionLevel.BALANCED,
    )
    data = json.loads(out)
    assert data.get("_ndjson_shape_summary") is True
    shapes = data["shapes"]
    keys = [tuple(s["keys"]) for s in shapes]
    assert keys == sorted(keys, key=lambda t: t)
    counts = {tuple(s["keys"]): s["count"] for s in shapes}
    assert counts[tuple(sorted(["a", "b"]))] == 2
    assert counts[("z",)] == 1
    ab_sample = next(s for s in shapes if tuple(s["keys"]) == ("a", "b"))["sample"]
    assert ab_sample["a"] == "int"
    assert ab_sample["b"] == "int"


def test_xml_safeguard_truncates_text_nodes_keeps_valid_xml() -> None:
    raw = "<root><item>short</item><item>" + ("x" * 400) + "</item></root>"
    strategy = XmlMachineSafeguardStrategy(text_max_len=50, min_bytes=32)
    out = strategy.compress(
        raw,
        context=_ctx(raw, content_type=ToolOutputContentType.XML),
        level=CompressionLevel.BALANCED,
    )
    ElementTree.fromstring(out)
    assert "x" * 200 not in out
    assert "short" in out


def test_xml_safeguard_fail_open_on_malformed() -> None:
    strategy = XmlMachineSafeguardStrategy(min_bytes=1)
    bad = "<root><unclosed>"
    assert (
        strategy.compress(
            bad,
            context=_ctx(bad, content_type=ToolOutputContentType.XML),
            level=CompressionLevel.BALANCED,
        )
        == bad
    )


def test_log_dedupe_collapses_repeated_normalized_lines() -> None:
    strategy = LogLineDedupeStrategy(min_repeat=3, min_bytes=10)
    lines = [
        "2024-01-01T00:00:00Z request ok",
        "2024-01-01T00:00:00Z request ok",
        "2024-01-01T00:00:00Z request ok",
        "unique line z",
    ]
    raw = "\n".join(lines)
    out = strategy.compress(
        raw,
        context=_ctx(
            raw, content_type=ToolOutputContentType.TEXT, command_signature="docker"
        ),
        level=CompressionLevel.BALANCED,
    )
    assert "x3" in out or "(x3)" in out
    assert "unique line z" in out


def test_log_dedupe_preserves_error_lines_unmerged() -> None:
    strategy = LogLineDedupeStrategy(min_repeat=2, min_bytes=10)
    lines = [
        "2024-01-01T00:00:01Z ok",
        "2024-01-01T00:00:02Z ok",
        "2024-01-01T00:00:03Z ERROR boom",
        "2024-01-01T00:00:04Z ERROR boom",
    ]
    raw = "\n".join(lines)
    out = strategy.compress(
        raw,
        context=_ctx(raw, content_type=ToolOutputContentType.TEXT),
        level=CompressionLevel.BALANCED,
    )
    assert out.count("ERROR boom") >= 2


def test_log_dedupe_normalizes_ids_hashes_and_ephemeral_paths_for_grouping() -> None:
    strategy = LogLineDedupeStrategy(min_repeat=3, min_bytes=1)
    lines = [
        (
            "2024-01-01T00:00:00Z INFO request_id=12345 "
            "job=11111111-1111-1111-1111-111111111111 "
            "hash=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
            "path=/tmp/build-123/result.log completed"
        ),
        (
            "2024-01-01T00:00:01Z INFO request_id=67890 "
            "job=22222222-2222-2222-2222-222222222222 "
            "hash=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb "
            "path=/var/tmp/build-456/result.log completed"
        ),
        (
            "2024-01-01T00:00:02Z INFO request_id=99999 "
            "job=33333333-3333-3333-3333-333333333333 "
            "hash=cccccccccccccccccccccccccccccccccccccccc "
            "path=C:\\Users\\mateusz\\AppData\\Local\\Temp\\build-789\\result.log completed"
        ),
        "tail line",
    ]
    raw = "\n".join(lines)
    out = strategy.compress(
        raw,
        context=_ctx(raw, content_type=ToolOutputContentType.TEXT),
        level=CompressionLevel.BALANCED,
    )
    assert "[log-dedupe repeated x3]" in out
    assert "tail line" in out


def test_sensitive_field_masks_values_without_leaking_raw_secrets() -> None:
    strategy = SensitiveFieldProjectionStrategy(
        skip_command_prefixes=("printenv path",),
    )
    raw = "API_KEY=supersecret\nPATH=/usr/bin\nPASSWORD=x\n"
    out = strategy.compress(
        raw,
        context=_ctx(
            raw,
            content_type=ToolOutputContentType.TEXT,
            command_signature="printenv",
            command_prefix="printenv",
        ),
        level=CompressionLevel.BALANCED,
    )
    assert "supersecret" not in out
    assert "API_KEY=***********" in out
    assert "PASSWORD=*" in out
    assert "[sensitive_projection]" not in out


def test_sensitive_field_allowlist_skips_projection() -> None:
    strategy = SensitiveFieldProjectionStrategy(
        skip_command_prefixes=("printenv path",),
    )
    raw = "API_KEY=visible\n"
    out = strategy.compress(
        raw,
        context=_ctx(
            raw,
            content_type=ToolOutputContentType.TEXT,
            command_signature="printenv",
            command_prefix="printenv path",
        ),
        level=CompressionLevel.BALANCED,
    )
    assert "visible" in out
    assert "[sensitive_projection]" not in out


def test_sensitive_field_projection_bypasses_explicit_format_requests() -> None:
    strategy = SensitiveFieldProjectionStrategy()
    raw = "API_KEY=supersecret\nPASSWORD=hunter2\n"
    out = strategy.compress(
        raw,
        context=_ctx(
            raw,
            content_type=ToolOutputContentType.TEXT,
            command_signature="printenv",
            command_prefix="printenv",
            explicit=True,
        ),
        level=CompressionLevel.BALANCED,
    )
    assert out == raw


def test_sensitive_field_projection_bypasses_non_text_payloads() -> None:
    strategy = SensitiveFieldProjectionStrategy()
    raw = json.dumps({"API_KEY": "supersecret"})
    out = strategy.compress(
        raw,
        context=_ctx(
            raw,
            content_type=ToolOutputContentType.JSON,
            command_signature="printenv",
            command_prefix="printenv",
        ),
        level=CompressionLevel.BALANCED,
    )
    assert out == raw


def test_sensitive_field_projection_fail_opens_on_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = SensitiveFieldProjectionStrategy()

    def _boom(_line: str) -> tuple[str, bool]:
        raise RuntimeError("mask failed")

    monkeypatch.setattr(strategy, "_maybe_mask_cloud_line", _boom)
    raw = "TOKEN  supersecret\n"
    out = strategy.compress(
        raw,
        context=_ctx(
            raw,
            content_type=ToolOutputContentType.TEXT,
            command_signature="aws",
            command_prefix="aws configure list",
        ),
        level=CompressionLevel.BALANCED,
    )
    assert out == raw


def test_rule_predicate_content_types_filters_rule() -> None:
    selector = RuleBasedStrategySelector()
    rule_json = CompressionRule(
        name="j",
        priority=10,
        when=CompressionRulePredicate(content_types=["json"], min_bytes=1),
        pipeline=["x"],
    )
    rule_text = CompressionRule(
        name="t",
        priority=20,
        when=CompressionRulePredicate(content_types=["text"], min_bytes=1),
        pipeline=["y"],
    )
    cfg = DynamicCompressionConfig(enabled=True, rules=[rule_text, rule_json])
    blob = json.dumps({"a": 1})
    ctx = _ctx(blob, content_type=ToolOutputContentType.JSON)
    selected_json = selector.select_rule(ctx, cfg)
    assert selected_json is not None
    assert selected_json.name == "j"
    ctx2 = _ctx("hello", content_type=ToolOutputContentType.TEXT)
    selected_text = selector.select_rule(ctx2, cfg)
    assert selected_text is not None
    assert selected_text.name == "t"
