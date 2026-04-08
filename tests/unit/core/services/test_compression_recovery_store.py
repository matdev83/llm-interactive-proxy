from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionRecoveryConfig,
)
from src.core.domain.dynamic_compression import (
    ToolIdentity,
    ToolOutputCompressionRecord,
)
from src.core.services.compression_recovery_store import CompressionRecoveryStore


def _config(tmp_path: Path, **overrides: object) -> CompressionRecoveryConfig:
    base = CompressionRecoveryConfig(
        mode="always",
        min_original_bytes=1,
        min_saved_bytes=1,
        max_artifact_bytes=32_768,
        max_artifacts=8,
        retention_seconds=3600,
        storage_dir=str(tmp_path),
        hint_in_text=False,
    )
    if not overrides:
        return base
    return base.model_copy(update=overrides)


def _record(
    *,
    tool_call_id: str = "tc-default",
    command_prefix: str = "curl https://internal.example.local/api --header token=secret",
    original_sha256: str = "a" * 64,
    compressed_sha256: str = "b" * 64,
    original_bytes: int = 4096,
    compressed_bytes: int = 2048,
    saved_bytes: int = 2048,
) -> ToolOutputCompressionRecord:
    return ToolOutputCompressionRecord(
        tool_call_id=tool_call_id,
        identity=ToolIdentity(
            tool_name="shell",
            tool_category="command_execution",
            command_signature="curl",
            command_prefix=command_prefix,
        ),
        original_bytes=original_bytes,
        compressed_bytes=compressed_bytes,
        saved_bytes=saved_bytes,
        original_sha256=original_sha256,
        compressed_sha256=compressed_sha256,
        applied=True,
    )


def _write_artifact(path: Path, *, created_at: float | None) -> None:
    payload: dict[str, object] = {
        "schema": "dynamic-compression-recovery-v1",
        "handle": path.stem,
        "content_encoding": "utf-8",
        "content_b64": "",
    }
    if created_at is not None:
        payload["created_at"] = created_at
    path.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_handle_and_metadata_are_redaction_safe(tmp_path: Path) -> None:
    store = CompressionRecoveryStore()
    record = _record(
        tool_call_id="tc-sensitive-user-123",
        command_prefix="curl https://secret.internal/path?api_key=topsecret",
    )
    handle, warning = await store.persist_if_eligible(
        original_content="diagnostic payload",
        record=record,
        config=_config(tmp_path),
    )

    assert warning is None
    assert handle is not None

    artifact_path = tmp_path / f"{handle}.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert payload["tool_call_id"] != "tc-sensitive-user-123"
    assert "tc-sensitive-user-123" not in payload["tool_call_id"]
    assert payload["command_prefix"] == "curl [args-redacted]"
    assert payload["command_prefix_fingerprint"]
    assert payload["metadata_redacted"] is True
    assert "secret.internal" not in artifact_path.read_text(encoding="utf-8")

    same_payload_different_ids = _record(
        tool_call_id="tc-other-sensitive-id",
        command_prefix="curl https://different.internal?token=other",
    )
    assert CompressionRecoveryStore._build_handle(
        record=record
    ) == CompressionRecoveryStore._build_handle(record=same_payload_different_ids)


@pytest.mark.asyncio
async def test_persisted_content_redacts_common_credentials(tmp_path: Path) -> None:
    store = CompressionRecoveryStore()
    content = "\n".join(
        [
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature",
            "OPENAI_API_KEY=example-api-key-123456",
            "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
            "password=super-secret-password",
            "diagnostic line keeps context",
        ]
    )

    handle, warning = await store.persist_if_eligible(
        original_content=content,
        record=_record(),
        config=_config(tmp_path),
    )

    assert warning is None
    assert handle is not None

    payload = json.loads((tmp_path / f"{handle}.json").read_text(encoding="utf-8"))
    decoded = base64.b64decode(payload["content_b64"]).decode("utf-8")

    assert payload["content_redacted"] is True
    assert "super-secret-password" not in decoded
    assert "AKIAIOSFODNN7EXAMPLE" not in decoded
    assert "example-api-key-123456" not in decoded
    assert "Authorization: Bearer eyJ" not in decoded
    assert "[REDACTED]" in decoded
    assert "diagnostic line keeps context" in decoded


@pytest.mark.asyncio
async def test_redaction_error_keeps_fail_open_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = CompressionRecoveryStore()

    def _boom(_: str) -> tuple[str, bool]:
        raise RuntimeError("redaction failed")

    monkeypatch.setattr(store, "_redact_sensitive_content", _boom)
    handle, warning = await store.persist_if_eligible(
        original_content="payload",
        record=_record(),
        config=_config(tmp_path),
    )

    assert handle is None
    assert warning is not None
    assert "failed open" in warning.lower()
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.asyncio
async def test_restart_like_pruning_enforces_max_artifacts(tmp_path: Path) -> None:
    now = 1_700_000_000.0
    _write_artifact(tmp_path / "111111111111111111111111.json", created_at=now - 300)
    _write_artifact(tmp_path / "222222222222222222222222.json", created_at=now - 200)
    _write_artifact(tmp_path / "333333333333333333333333.json", created_at=now - 100)

    # New store instance simulates process restart with empty in-memory cache.
    store = CompressionRecoveryStore()
    handle, warning = await store.persist_if_eligible(
        original_content="payload",
        record=_record(),
        config=_config(tmp_path, max_artifacts=2, retention_seconds=2_000_000_000),
    )

    assert warning is None
    assert handle is not None

    files = sorted(path.name for path in tmp_path.glob("*.json"))
    assert files == [f"{handle}.json", "333333333333333333333333.json"]


@pytest.mark.asyncio
async def test_restart_like_pruning_removes_expired_artifacts(tmp_path: Path) -> None:
    _write_artifact(tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaa.json", created_at=1.0)
    _write_artifact(tmp_path / "bbbbbbbbbbbbbbbbbbbbbbbb.json", created_at=None)

    store = CompressionRecoveryStore()
    handle, warning = await store.persist_if_eligible(
        original_content="payload",
        record=_record(
            original_sha256="c" * 64,
            compressed_sha256="d" * 64,
            saved_bytes=1024,
        ),
        config=_config(tmp_path, max_artifacts=8, retention_seconds=60),
    )

    assert warning is None
    assert handle is not None

    files = sorted(path.name for path in tmp_path.glob("*.json"))
    assert files == [f"{handle}.json", "bbbbbbbbbbbbbbbbbbbbbbbb.json"]
