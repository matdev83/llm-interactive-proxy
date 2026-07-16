"""Unit tests for openai-codex early session verbosity bump helper."""

from __future__ import annotations

from types import SimpleNamespace

from src.connectors.openai_codex.early_session_verbosity_bump import (
    DEFAULT_EARLY_SESSION_VERBOSITY_BUMP,
    EARLY_SESSION_BUMP_FORCED_PARAMS,
    is_openai_codex_responses_family,
    normalize_early_session_verbosity_bump,
    should_apply_early_session_verbosity_bump,
)


class TestNormalizeEarlySessionVerbosityBump:
    def test_defaults_when_missing(self) -> None:
        assert normalize_early_session_verbosity_bump(None) == {
            "enabled": True,
            "max_turns": 5,
        }

    def test_defaults_match_constant(self) -> None:
        assert (
            normalize_early_session_verbosity_bump({})
            == DEFAULT_EARLY_SESSION_VERBOSITY_BUMP
        )

    def test_merges_yaml_overrides(self) -> None:
        assert normalize_early_session_verbosity_bump(
            {"enabled": False, "max_turns": 3}
        ) == {"enabled": False, "max_turns": 3}

    def test_invalid_max_turns_falls_back(self) -> None:
        assert (
            normalize_early_session_verbosity_bump({"max_turns": "nope"})["max_turns"]
            == 5
        )

    def test_non_positive_max_turns_clamped_to_zero(self) -> None:
        assert (
            normalize_early_session_verbosity_bump({"max_turns": -1})["max_turns"] == 0
        )


class TestIsOpenaiCodexResponsesFamily:
    def test_matches_base_and_v2(self) -> None:
        assert is_openai_codex_responses_family("openai-codex") is True
        assert is_openai_codex_responses_family("openai_codex") is True
        assert is_openai_codex_responses_family("openai-codex-v2") is True
        assert is_openai_codex_responses_family("openai_codex_v2") is True

    def test_matches_multi_instance(self) -> None:
        assert is_openai_codex_responses_family("openai-codex.1") is True
        assert is_openai_codex_responses_family("openai-codex-v2.3") is True

    def test_excludes_app_server_and_others(self) -> None:
        assert is_openai_codex_responses_family("openai-codex-app-server") is False
        assert is_openai_codex_responses_family("openai") is False
        assert is_openai_codex_responses_family("") is False
        assert is_openai_codex_responses_family(None) is False


class TestShouldApplyEarlySessionVerbosityBump:
    def test_missing_session_applies_when_enabled(self) -> None:
        assert (
            should_apply_early_session_verbosity_bump(
                session=None,
                backend_type="openai-codex",
                config={"enabled": True, "max_turns": 5},
            )
            is True
        )

    def test_disabled_never_applies(self) -> None:
        session = SimpleNamespace(history=[])
        assert (
            should_apply_early_session_verbosity_bump(
                session=session,
                backend_type="openai-codex",
                config={"enabled": False, "max_turns": 5},
            )
            is False
        )

    def test_wrong_family_never_applies(self) -> None:
        assert (
            should_apply_early_session_verbosity_bump(
                session=SimpleNamespace(history=[]),
                backend_type="openai-codex-app-server",
                config={"enabled": True, "max_turns": 5},
            )
            is False
        )

    def test_turn_window_boundary(self) -> None:
        cfg = {"enabled": True, "max_turns": 5}
        for n in range(5):
            session = SimpleNamespace(history=[object()] * n)
            assert (
                should_apply_early_session_verbosity_bump(
                    session=session,
                    backend_type="openai-codex",
                    config=cfg,
                )
                is True
            ), f"expected apply at history_len={n}"

        session = SimpleNamespace(history=[object()] * 5)
        assert (
            should_apply_early_session_verbosity_bump(
                session=session,
                backend_type="openai-codex",
                config=cfg,
            )
            is False
        )

    def test_forced_params_constant(self) -> None:
        assert EARLY_SESSION_BUMP_FORCED_PARAMS == {
            "temperature": 1.0,
            "verbosity": "high",
        }
