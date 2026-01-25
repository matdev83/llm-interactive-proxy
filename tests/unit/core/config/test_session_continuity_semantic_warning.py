from __future__ import annotations

import logging

from src.core.config.semantic_validation import validate_config_semantics


def test_validate_config_semantics_warns_when_topic_similarity_enabled(
    caplog, tmp_path
):
    cfg = {
        "session": {
            "session_continuity": {
                "enable_topic_similarity_matching": True,
            }
        }
    }

    with caplog.at_level(logging.WARNING):
        validate_config_semantics(cfg, tmp_path / "config.yaml")

    assert any(
        "session.session_continuity.enable_topic_similarity_matching=true"
        in rec.message
        for rec in caplog.records
    )


def test_validate_config_semantics_no_warning_by_default(caplog, tmp_path):
    cfg = {
        "session": {
            "session_continuity": {
                "enable_topic_similarity_matching": False,
            }
        }
    }

    with caplog.at_level(logging.WARNING):
        validate_config_semantics(cfg, tmp_path / "config.yaml")

    assert not any(
        "session.session_continuity.enable_topic_similarity_matching=true"
        in rec.message
        for rec in caplog.records
    )
