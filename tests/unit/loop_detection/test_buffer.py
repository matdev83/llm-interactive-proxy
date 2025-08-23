from collections import deque

from src.loop_detection.buffer import ResponseBuffer


def test_response_buffer_init() -> None:
    buffer = ResponseBuffer(max_size=10)
    assert buffer.max_size == 10
    assert buffer.buffer == deque(maxlen=10)
    assert buffer.total_length == 0
    assert buffer.stored_length == 0


def test_response_buffer_append_within_max_size() -> None:
    buffer = ResponseBuffer(max_size=10)
    buffer.append("hello")
    assert buffer.get_content() == "hello"
    assert buffer.total_length == 5
    assert buffer.stored_length == 5
    buffer.append("world")
    assert buffer.get_content() == "helloworld"
    assert buffer.total_length == 10
    assert buffer.stored_length == 10


def test_response_buffer_append_exceeds_max_size() -> None:
    buffer = ResponseBuffer(max_size=10)
    buffer.append("0123456789")  # 10 chars
    assert buffer.get_content() == "0123456789"
    buffer.append("abc")  # 3 chars, exceeds by 3
    assert buffer.get_content() == "3456789abc"  # "012" removed
    assert buffer.total_length == 13  # Total appended
    assert buffer.stored_length == 10  # Current stored


def test_response_buffer_clear() -> None:
    buffer = ResponseBuffer(max_size=10)
    buffer.append("test")
    buffer.clear()
    assert buffer.get_content() == ""
    assert buffer.total_length == 0
    assert buffer.stored_length == 0


def test_response_buffer_get_recent_content() -> None:
    buffer = ResponseBuffer(max_size=20)
    buffer.append("abcdefghijklmnopqrst")  # 20 chars
    assert buffer.get_recent_content(5) == "pqrst"
    assert buffer.get_recent_content(20) == "abcdefghijklmnopqrst"
    assert (
        buffer.get_recent_content(30) == "abcdefghijklmnopqrst"
    )  # Requesting more than available


def test_response_buffer_empty_append() -> None:
    buffer = ResponseBuffer(max_size=10)
    buffer.append("")
    assert buffer.get_content() == ""
    assert buffer.total_length == 0
    assert buffer.stored_length == 0


def test_response_buffer_multiple_small_appends_exceeding_max_size() -> None:
    buffer = ResponseBuffer(max_size=5)
    buffer.append("a")
    buffer.append("b")
    buffer.append("c")
    buffer.append("d")
    buffer.append("e")
    assert buffer.get_content() == "abcde"
    buffer.append("f")  # "a" should be removed
    assert buffer.get_content() == "bcdef"
    buffer.append("g")  # "b" should be removed
    assert buffer.get_content() == "cdefg"
