from __future__ import annotations

import re

import pytest
from src.core.services.b2bua_session_id_factory import B2BUASessionIdFactory


def test_generate_a_session_id_format() -> None:
    factory = B2BUASessionIdFactory()

    a_session_id = factory.generate_a_session_id()

    assert re.fullmatch(
        r"llm-b2bua-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        a_session_id,
    )


def test_generate_b_session_id_embeds_a_uuid_and_sequence() -> None:
    factory = B2BUASessionIdFactory()
    a_session_id = "llm-b2bua-12345678-1234-1234-1234-123456789abc"

    b_session_id = factory.generate_b_session_id(a_session_id, seq=7)

    assert b_session_id == "llm-b2bua-b-12345678-1234-1234-1234-123456789abc-7"


def test_generate_b_session_id_rejects_invalid_a_session_id() -> None:
    factory = B2BUASessionIdFactory()

    with pytest.raises(ValueError, match="Invalid a_session_id format"):
        factory.generate_b_session_id("bad-a-id", seq=1)


def test_generate_b_session_id_rejects_non_positive_sequence() -> None:
    factory = B2BUASessionIdFactory()
    a_session_id = "llm-b2bua-12345678-1234-1234-1234-123456789abc"

    with pytest.raises(ValueError, match="seq must be >= 1"):
        factory.generate_b_session_id(a_session_id, seq=0)


def test_generated_ids_are_http_header_safe() -> None:
    factory = B2BUASessionIdFactory()
    a_session_id = factory.generate_a_session_id()
    b_session_id = factory.generate_b_session_id(a_session_id, seq=1)

    assert re.fullmatch(r"[A-Za-z0-9-]+", a_session_id)
    assert re.fullmatch(r"[A-Za-z0-9-]+", b_session_id)


def test_is_canonical_a_session_id_accepts_valid_a_leg() -> None:
    factory = B2BUASessionIdFactory()
    assert factory.is_canonical_a_session_id(
        "llm-b2bua-12345678-1234-1234-1234-123456789abc"
    )


def test_is_canonical_a_session_id_rejects_b_leg_and_garbage() -> None:
    factory = B2BUASessionIdFactory()
    assert not factory.is_canonical_a_session_id(
        "llm-b2bua-b-12345678-1234-1234-1234-123456789abc-1"
    )
    assert not factory.is_canonical_a_session_id("not-a-session")
    assert not factory.is_canonical_a_session_id("")
