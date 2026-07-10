"""Catalog discovery service.

Runs ``codex debug models`` via the resolved codex binary and parses stdout into
a :class:`CodexModelCatalog`. Returns ``None`` on any failure (binary missing,
timeout, non-zero exit, malformed output, parse error) so the provider can fall
back to the shipped snapshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess

from src.connectors.codex_helpers import candidate_codex_executables
from src.connectors.openai_codex.catalog.interfaces import ICodexCatalogParser
from src.connectors.openai_codex.catalog.parser import CodexCatalogParser
from src.connectors.openai_codex.catalog.types import CodexModelCatalog

logger = logging.getLogger(__name__)


class CodexCatalogDiscoveryService:
    """Discover the catalog at runtime by shelling out to ``codex debug models``."""

    def __init__(
        self,
        *,
        codex_binary_path: str | None = None,
        timeout_seconds: float = 10.0,
        parser: ICodexCatalogParser | None = None,
    ) -> None:
        self._codex_binary_path = codex_binary_path
        self._timeout_seconds = timeout_seconds
        self._parser = parser if parser is not None else CodexCatalogParser()

    async def discover(self) -> CodexModelCatalog | None:
        candidates = candidate_codex_executables(self._codex_binary_path)
        if not candidates:
            logger.debug(
                "Codex catalog discovery skipped: no codex binary found on PATH/CODEX_BIN"
            )
            return None
        executable = candidates[0]

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [executable, "debug", "models"],
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
                shell=False,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Codex catalog discovery timed out after %ss; falling back.",
                self._timeout_seconds,
            )
            return None
        except OSError as exc:
            logger.warning("Codex catalog discovery subprocess failed: %s", exc)
            return None

        if result.returncode != 0:
            logger.warning(
                "Codex catalog discovery exited with code %s; falling back. stderr=%s",
                result.returncode,
                (result.stderr or "").strip(),
            )
            return None

        stdout = result.stdout or ""
        if not stdout.strip():
            logger.warning(
                "Codex catalog discovery returned empty stdout; falling back."
            )
            return None

        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError as exc:
            logger.warning("Codex catalog discovery stdout is not valid JSON: %s", exc)
            return None

        try:
            return self._parser.parse(raw)
        except Exception as exc:  # - fall back on any parse failure
            logger.warning(
                "Codex catalog discovery parse failed: %s", exc, exc_info=True
            )
            return None


__all__ = ["CodexCatalogDiscoveryService"]
