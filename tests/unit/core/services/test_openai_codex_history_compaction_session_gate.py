"""Tests for openai-codex session gate on history context compaction."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session, SessionState
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintService,
)
from src.core.services.request_processor_service import (
    _coerce_history_compaction_session_allowed,
)
from src.core.services.session_manager_service import SessionManager


@pytest.fixture
def session_service() -> AsyncMock:
    mock = AsyncMock()
    mock.update_session = AsyncMock()
    return mock


@pytest.fixture
def session_manager(session_service: AsyncMock) -> SessionManager:
    return SessionManager(
        session_service=session_service,
        session_resolver=AsyncMock(),
        fingerprint_service=ConversationFingerprintService(),
        session_repository=None,
    )


def _make_session(session_id: str = "s1") -> Session:
    state = SessionState(
        backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
        reasoning_config=ReasoningConfiguration(),
        loop_config=LoopDetectionConfiguration(),
    )
    return Session(session_id=session_id, state=state)


@pytest.mark.asyncio
async def test_non_codex_backend_leaves_flag_and_skips_persist(
    session_manager: SessionManager,
    session_service: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _make_session()
    with caplog.at_level(logging.WARNING):
        out = await session_manager.apply_openai_codex_history_compaction_gate(
            session, "openai"
        )
    assert out is session
    assert session.state.history_compaction_allowed is True
    session_service.update_session.assert_not_awaited()
    assert not any(
        "Disabled history context compaction" in r.message for r in caplog.records
    )


@pytest.mark.parametrize(
    "backend",
    ("openai-codex", "openai_codex", "openai-codex.1", "OPENAI_CODEX.2"),
)
@pytest.mark.asyncio
async def test_codex_backend_flips_once_and_logs_once(
    session_manager: SessionManager,
    session_service: AsyncMock,
    backend: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _make_session("sess-codex")
    with caplog.at_level(logging.WARNING):
        await session_manager.apply_openai_codex_history_compaction_gate(
            session, backend
        )
    assert session.state.history_compaction_allowed is False
    session_service.update_session.assert_awaited_once()
    assert (
        sum(
            1
            for r in caplog.records
            if "Disabled history context compaction" in r.message
            and "sess-codex" in r.message
        )
        == 1
    )

    session_service.reset_mock()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await session_manager.apply_openai_codex_history_compaction_gate(
            session, "openai-codex"
        )
    session_service.update_session.assert_not_awaited()
    assert not caplog.records


@pytest.mark.asyncio
async def test_already_disabled_skips_persist_and_log(
    session_manager: SessionManager,
    session_service: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _make_session()
    session.update_state(session.state.with_history_compaction_allowed(False))
    with caplog.at_level(logging.WARNING):
        await session_manager.apply_openai_codex_history_compaction_gate(
            session, "openai-codex"
        )
    session_service.update_session.assert_not_awaited()
    assert not caplog.records


@pytest.mark.asyncio
async def test_codex_gate_reverts_state_when_persist_fails(
    session_manager: SessionManager,
    session_service: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _make_session("sess-persist-fail")
    session_service.update_session = AsyncMock(side_effect=RuntimeError("db down"))
    with caplog.at_level(logging.WARNING):
        await session_manager.apply_openai_codex_history_compaction_gate(
            session, "openai-codex"
        )
    assert session.state.history_compaction_allowed is True
    session_service.update_session.assert_awaited_once()
    assert any(
        "Failed to persist history compaction disable" in r.message
        for r in caplog.records
    )
    assert not any(
        "Disabled history context compaction for the remainder" in r.message
        for r in caplog.records
    )


def test_coerce_history_compaction_session_allowed_numpy_false() -> None:
    np = pytest.importorskip("numpy")
    m = MagicMock()
    m.history_compaction_allowed = np.bool_(False)
    assert _coerce_history_compaction_session_allowed(m) is False


def test_coerce_history_compaction_session_allowed_numpy_true() -> None:
    np = pytest.importorskip("numpy")
    m = MagicMock()
    m.history_compaction_allowed = np.bool_(True)
    assert _coerce_history_compaction_session_allowed(m) is True


def test_coerce_history_compaction_session_allowed_mock_defaults_true() -> None:
    m = MagicMock(spec=["history_compaction_allowed"])
    m.history_compaction_allowed = MagicMock()
    assert _coerce_history_compaction_session_allowed(m) is True
