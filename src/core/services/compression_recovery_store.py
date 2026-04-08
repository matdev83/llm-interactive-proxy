"""Bounded retention store for dynamic compression recovery artifacts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionRecoveryConfig,
)
from src.core.domain.dynamic_compression import ToolOutputCompressionRecord


@dataclass
class _RecoveryArtifact:
    handle: str
    created_at: float
    path: Path


_HANDLE_PATTERN = re.compile(r"^[0-9a-f]{24}$")
_SENSITIVE_CONTENT_REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?im)(authorization\s*:\s*bearer\s+)([a-z0-9._~+/\-=]+)"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"(?im)\b((?:(?:[a-z0-9]+[_-])*(?:api[_-]?key|token|password|secret|client[_-]?secret|access[_-]?token|refresh[_-]?token))\b\s*[:=]\s*)([^\s\"';]+)"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED]",
    ),
    (
        re.compile(
            r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"
        ),
        "-----BEGIN PRIVATE KEY-----\n[REDACTED]\n-----END PRIVATE KEY-----",
    ),
)


class CompressionRecoveryStore:
    """Persist bounded raw-output artifacts and emit recovery handles."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._artifacts: dict[str, _RecoveryArtifact] = {}

    async def persist_if_eligible(
        self,
        *,
        original_content: str,
        record: ToolOutputCompressionRecord,
        config: CompressionRecoveryConfig,
    ) -> tuple[str | None, str | None]:
        """Persist an artifact when recovery policy and thresholds allow it."""
        return await asyncio.to_thread(
            self._persist_if_eligible_sync,
            original_content=original_content,
            record=record,
            config=config,
        )

    def _persist_if_eligible_sync(
        self,
        *,
        original_content: str,
        record: ToolOutputCompressionRecord,
        config: CompressionRecoveryConfig,
    ) -> tuple[str | None, str | None]:
        if config.mode == "never":
            return None, None
        if record.original_bytes < config.min_original_bytes:
            return None, None
        if record.saved_bytes < config.min_saved_bytes:
            return None, None
        if config.mode == "failures" and not (
            record.failed_open or record.fallback_applied
        ):
            return None, None

        now = time.time()
        handle = self._build_handle(record=record)
        artifact_dir = Path(config.storage_dir)
        artifact_path = artifact_dir / f"{handle}.json"

        with self._lock:
            try:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                self._refresh_artifacts_from_disk_locked(artifact_dir=artifact_dir)
                self._prune_locked(now=now, config=config)
                if handle in self._artifacts and artifact_path.exists():
                    return handle, None

                redacted_content, content_redacted = self._redact_sensitive_content(
                    original_content
                )
                raw_bytes = redacted_content.encode("utf-8", errors="replace")
                bounded_bytes = raw_bytes[: config.max_artifact_bytes]
                payload = {
                    "schema": "dynamic-compression-recovery-v1",
                    "created_at": now,
                    "handle": handle,
                    "tool_call_id": self._fingerprint_identifier(record.tool_call_id),
                    "tool_name": record.identity.tool_name,
                    "tool_category": record.identity.tool_category,
                    "command_signature": record.identity.command_signature,
                    "command_prefix": self._redacted_command_prefix(
                        command_prefix=record.identity.command_prefix,
                        command_signature=record.identity.command_signature,
                    ),
                    "command_prefix_fingerprint": self._fingerprint_identifier(
                        record.identity.command_prefix
                    ),
                    "metadata_redacted": True,
                    "original_sha256": record.original_sha256,
                    "compressed_sha256": record.compressed_sha256,
                    "original_bytes": record.original_bytes,
                    "compressed_bytes": record.compressed_bytes,
                    "saved_bytes": record.saved_bytes,
                    "failed_open": record.failed_open,
                    "fallback_applied": record.fallback_applied,
                    "content_encoding": "utf-8",
                    "content_b64": base64.b64encode(bounded_bytes).decode("ascii"),
                    "content_redacted": content_redacted,
                    "content_truncated": len(raw_bytes) > len(bounded_bytes),
                    "content_bytes_total": len(raw_bytes),
                }
                artifact_path.write_text(
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                self._artifacts[handle] = _RecoveryArtifact(
                    handle=handle,
                    created_at=now,
                    path=artifact_path,
                )
                self._prune_locked(now=now, config=config)
                return handle, None
            except Exception as exc:
                warning = (
                    "Compression recovery artifact persistence failed open: "
                    f"{exc.__class__.__name__}"
                )
                return None, warning

    @staticmethod
    def _build_handle(*, record: ToolOutputCompressionRecord) -> str:
        digest_source = "|".join(
            [
                record.identity.tool_name,
                record.identity.tool_category,
                record.identity.command_signature or "-",
                record.original_sha256 or "-",
                record.compressed_sha256 or "-",
                str(record.original_bytes),
                str(record.compressed_bytes),
                str(record.saved_bytes),
            ]
        )
        return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _fingerprint_identifier(value: str | None) -> str | None:
        if not value:
            return None
        digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
        return f"sha256:{digest[:16]}"

    @classmethod
    def _redacted_command_prefix(
        cls,
        *,
        command_prefix: str | None,
        command_signature: str | None,
    ) -> str | None:
        signature = (command_signature or "").strip()
        if signature:
            return f"{signature} [args-redacted]"
        if not command_prefix:
            return None
        first_token = command_prefix.strip().split(maxsplit=1)[0]
        if not first_token:
            return None
        return f"{first_token} [args-redacted]"

    @staticmethod
    def _redact_sensitive_content(content: str) -> tuple[str, bool]:
        redacted_content = content
        redacted = False
        for pattern, replacement in _SENSITIVE_CONTENT_REDACTION_RULES:
            redacted_content, substitutions = pattern.subn(
                replacement, redacted_content
            )
            if substitutions > 0:
                redacted = True
        return redacted_content, redacted

    def _refresh_artifacts_from_disk_locked(self, *, artifact_dir: Path) -> None:
        if not artifact_dir.exists():
            self._artifacts = {}
            return

        discovered: dict[str, _RecoveryArtifact] = {}
        for artifact_path in sorted(
            artifact_dir.glob("*.json"), key=lambda path: path.name
        ):
            if not artifact_path.is_file():
                continue
            handle = artifact_path.stem
            if _HANDLE_PATTERN.fullmatch(handle) is None:
                continue
            discovered[handle] = _RecoveryArtifact(
                handle=handle,
                created_at=self._read_created_at_from_disk(artifact_path),
                path=artifact_path,
            )
        self._artifacts = discovered

    @staticmethod
    def _read_created_at_from_disk(artifact_path: Path) -> float:
        fallback = time.time()
        with suppress(Exception):
            fallback = float(artifact_path.stat().st_mtime)

        with suppress(Exception):
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            created_at = payload.get("created_at")
            if isinstance(created_at, int | float):
                return float(created_at)
        return fallback

    def _prune_locked(
        self,
        *,
        now: float,
        config: CompressionRecoveryConfig,
    ) -> None:
        expired_handles = [
            handle
            for handle, artifact in self._artifacts.items()
            if (now - artifact.created_at) >= float(config.retention_seconds)
        ]
        for handle in expired_handles:
            self._remove_locked(handle)

        while len(self._artifacts) > config.max_artifacts:
            oldest = min(
                self._artifacts.values(),
                key=lambda artifact: (artifact.created_at, artifact.handle),
            )
            self._remove_locked(oldest.handle)

    def _remove_locked(self, handle: str) -> None:
        artifact = self._artifacts.pop(handle, None)
        if artifact is None:
            return
        with suppress(Exception):
            artifact.path.unlink(missing_ok=True)
