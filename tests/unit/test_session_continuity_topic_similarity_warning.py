"""Ensure CLI warns when risky session continuity options are enabled."""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig


def test_cli_warns_when_topic_similarity_matching_enabled(caplog):
    from src.core.cli import _warn_if_topic_similarity_matching_enabled

    cfg = AppConfig(
        {
            "session": {
                "session_continuity": {
                    "enable_topic_similarity_matching": True,
                }
            }
        }
    )

    with caplog.at_level(logging.WARNING):
        _warn_if_topic_similarity_matching_enabled(cfg)

    assert any(
        "session.session_continuity.enable_topic_similarity_matching=true"
        in rec.message
        for rec in caplog.records
    )


def test_cli_does_not_warn_by_default(caplog):
    from src.core.cli import _warn_if_topic_similarity_matching_enabled

    cfg = AppConfig()

    with caplog.at_level(logging.WARNING):
        _warn_if_topic_similarity_matching_enabled(cfg)

    assert not any(
        "session.session_continuity.enable_topic_similarity_matching=true"
        in rec.message
        for rec in caplog.records
    )
