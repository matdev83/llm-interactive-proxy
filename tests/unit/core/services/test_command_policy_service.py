from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from src.core.config.app_config import AppConfig, BackendSettings, SessionConfig
from src.core.domain.session import Session
from src.core.services.command_policy_service import CommandPolicyService


@dataclass
class DummyAppState:
    command_prefix: str | None = None
    disable_interactive: bool = False

    def get_command_prefix(self) -> str | None:
        return self.command_prefix

    def get_disable_interactive_commands(self) -> bool:
        return self.disable_interactive

    def get_setting(self, key: str, default: Any = None) -> Any:
        return default


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STATIC_ROUTE", raising=False)
    monkeypatch.delenv("STRICT_COMMAND_DETECTION", raising=False)
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)


def build_policy(
    *,
    backends: BackendSettings | None = None,
    session_cfg: SessionConfig | None = None,
    app_state: DummyAppState | None = None,
) -> CommandPolicyService:
    config = AppConfig(
        backends=backends or BackendSettings(),
        session=session_cfg or SessionConfig(),
    )
    return CommandPolicyService(config=config, app_state=app_state)


def test_static_route_detects_config_value() -> None:
    policy = build_policy(backends=BackendSettings(static_route="backend:model"))
    assert policy.is_static_route_enforced() is True


def test_static_route_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATIC_ROUTE", "openai:gpt-4")
    policy = build_policy()
    assert policy.is_static_route_enforced() is True


def test_static_route_ignores_blank_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATIC_ROUTE", "   ")
    policy = build_policy()
    assert policy.is_static_route_enforced() is False


def test_interactive_commands_disabled_prefers_app_state() -> None:
    policy = build_policy(
        session_cfg=SessionConfig(disable_interactive_commands=False),
        app_state=DummyAppState(disable_interactive=True),
    )
    assert policy.are_interactive_commands_disabled() is True


def test_interactive_commands_disabled_falls_back_to_config() -> None:
    policy = build_policy(
        session_cfg=SessionConfig(disable_interactive_commands=True),
        app_state=DummyAppState(disable_interactive=False),
    )
    assert policy.are_interactive_commands_disabled() is True


def test_strict_detection_prefers_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRICT_COMMAND_DETECTION", "TrUe")
    policy = build_policy()
    assert policy.should_apply_strict_detection() is True


def test_strict_detection_handles_false_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRICT_COMMAND_DETECTION", "0")
    policy = build_policy(
        session_cfg=SessionConfig(),
    )
    assert policy.should_apply_strict_detection() is False


def test_resolve_command_prefix_prefers_session_override() -> None:
    session = Session(session_id="abc")
    session.state = session.state.with_command_prefix_override("!test")
    policy = build_policy(app_state=DummyAppState(command_prefix="!app"))
    result = policy.resolve_command_prefix(session=session, fallback_prefix="!default")
    assert result == "!test"


def test_resolve_command_prefix_consults_app_state() -> None:
    policy = build_policy(app_state=DummyAppState(command_prefix="!app"))
    session = Session(session_id="abc")
    result = policy.resolve_command_prefix(session=session, fallback_prefix="!default")
    assert result == "!app"


def test_resolve_command_prefix_uses_config_then_fallback() -> None:
    policy = CommandPolicyService(
        config=AppConfig(command_prefix="!cfg"),
        app_state=None,
    )
    session = Session(session_id="abc")
    session.state = session.state.with_command_prefix_override(None)
    assert (
        policy.resolve_command_prefix(session=session, fallback_prefix="!default")
        == "!cfg"
    )

    fallback_policy = CommandPolicyService(
        config=AppConfig(command_prefix=""),
        app_state=None,
    )
    fallback_result = fallback_policy.resolve_command_prefix(
        session=session, fallback_prefix="!default"
    )
    assert fallback_result == "!default"
