from __future__ import annotations

from src.core.utils.json_intent import (
    infer_expected_json,
    is_json_content_type,
    is_json_like,
    set_expected_json,
)


def test_is_json_like() -> None:
    assert is_json_like('{"a":1}')
    assert is_json_like(" [1,2,3] ")
    assert not is_json_like("foo")
    assert not is_json_like("")


def test_is_json_content_type() -> None:
    assert is_json_content_type({"content_type": "application/json"})
    assert is_json_content_type(
        {"headers": {"Content-Type": "application/json; charset=utf-8"}}
    )
    assert not is_json_content_type({})


def test_infer_expected_json() -> None:
    assert infer_expected_json({"content_type": "application/json"}, None)
    assert infer_expected_json({}, '{"a":1}')
    assert not infer_expected_json({}, "foo")


def test_set_expected_json() -> None:
    md = {}
    set_expected_json(md, True)
    assert md["expected_json"] is True
