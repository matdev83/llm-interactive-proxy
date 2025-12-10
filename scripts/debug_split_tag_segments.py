"""Debug script to verify _split_tag_segments behavior with newlines."""

import sys

sys.path.insert(0, ".")


def _split_tag_segments(buffer: str, tag_name: str) -> tuple[str, str]:
    if not buffer:
        return "", ""

    parts: list[str] = []
    idx = 0
    length = len(buffer)
    pending_tail = ""
    open_tag = f"<{tag_name}"
    close_tag = f"</{tag_name}>"

    while idx < length:
        start = buffer.find(open_tag, idx)
        if start == -1:
            parts.append(buffer[idx:])
            pending_tail = ""
            break

        if start > idx:
            parts.append(buffer[idx:start])

        end = buffer.find(close_tag, start)
        if end == -1:
            pending_tail = buffer[start:]
            break

        end += len(close_tag)
        parts.append(buffer[start:end])
        idx = end

        if idx >= length:
            pending_tail = ""
            break

    return "".join(parts), pending_tail


# Test with newline
result = _split_tag_segments("\n", "tool")
print("Input: '\\n'")
print(f"Result: {result!r}")
print(f"Emit text: {result[0]!r}")
print(f"Pending tail: {result[1]!r}")

# Test with dash
result_dash = _split_tag_segments("-", "tool")
print("\nInput: '-'")
print(f"Result: {result_dash!r}")
