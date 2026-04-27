"""Unit tests for gpt-5.5 ChatGPT-account Codex downgrade helpers."""

from __future__ import annotations

from src.connectors.openai_codex.gpt55_account_compatibility import (
    Gpt55FreePlanDowngradeConfig,
    codex_plan_type_hint_from_account_payloads,
    extract_codex_error_detail_string,
    gpt55_config_from_mapping,
    is_upstream_gpt55_chatgpt_rejection,
    maybe_reactive_gpt55_downgrade,
    plan_hint_is_free,
    should_downgrade_source_model,
)


def test_is_upstream_gpt55_chatgpt_rejection_exact_log_message() -> None:
    d = {
        "detail": (
            "The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account."
        )
    }
    assert is_upstream_gpt55_chatgpt_rejection(d) is True


def test_is_upstream_rejects_unrelated_400() -> None:
    assert (
        is_upstream_gpt55_chatgpt_rejection({"detail": "Instructions are not valid"})
        is False
    )


def test_extract_detail_after_instruction_mapping_shape() -> None:
    """Executor maps only instruction errors; gpt-5.5 body stays a plain detail string."""
    wrapped = {
        "error": "codex_instructions_invalid",
        "original_error": {
            "detail": (
                "The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account."
            )
        },
    }
    assert is_upstream_gpt55_chatgpt_rejection(wrapped) is True


def test_plan_hint_is_free() -> None:
    cfg = Gpt55FreePlanDowngradeConfig(free_plan_types=frozenset({"free"}))
    assert plan_hint_is_free("free", cfg.free_plan_types) is True
    assert plan_hint_is_free("FREE", cfg.free_plan_types) is True
    assert plan_hint_is_free("plus", cfg.free_plan_types) is False
    assert plan_hint_is_free(None, cfg.free_plan_types) is False
    assert plan_hint_is_free(object(), cfg.free_plan_types) is False


def test_codex_plan_type_hint_from_headers_then_usage() -> None:
    h = {"x-codex-plan-type": "plus"}
    assert codex_plan_type_hint_from_account_payloads(h, None) == "plus"
    h2: dict[str, str] = {}
    ul: dict[str, object] = {"plan_type": "free"}
    assert codex_plan_type_hint_from_account_payloads(h2, ul) == "free"


def test_should_downgrade_source_model() -> None:
    cfg = Gpt55FreePlanDowngradeConfig()
    assert should_downgrade_source_model(current_model="gpt-5.5", config=cfg) is True
    assert should_downgrade_source_model(current_model="gpt-5.4", config=cfg) is False


def test_maybe_reactive_gpt55_downgrade() -> None:
    cfg = Gpt55FreePlanDowngradeConfig()
    assert (
        maybe_reactive_gpt55_downgrade(
            current_model="gpt-5.5",
            config=cfg,
            recovery_already_used=False,
        )
        == "gpt-5.4"
    )
    assert (
        maybe_reactive_gpt55_downgrade(
            current_model="gpt-5.5",
            config=cfg,
            recovery_already_used=True,
        )
        is None
    )


def test_gpt55_config_from_mapping() -> None:
    c = gpt55_config_from_mapping(
        {
            "enabled": False,
            "source_model": "gpt-5.5",
            "target_model": "gpt-5.4",
            "free_plan_types": ["free", "anon"],
        }
    )
    assert c.enabled is False
    assert "anon" in c.free_plan_types


def test_extract_codex_error_detail_string() -> None:
    assert extract_codex_error_detail_string({"detail": "x"}) == "x"
