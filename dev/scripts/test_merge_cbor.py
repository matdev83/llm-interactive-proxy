import json
from typing import Any

def _to_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict):
                blocks.append(dict(item))
            elif isinstance(item, str) and item:
                blocks.append({"type": "text", "text": item})
        return blocks
    elif isinstance(content, str):
        if content:
            return [{"type": "text", "text": content}]
        return []
    elif content is not None:
        return [{"type": "text", "text": str(content)}]
    return []


def _merge_consecutive_anthropic_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not messages:
        return []

    merged: list[dict[str, Any]] = []
    for msg in messages:
        if not merged:
            merged.append(dict(msg))
            continue

        prev_msg = merged[-1]
        if prev_msg.get("role") == msg.get("role"):
            prev_blocks = _to_content_blocks(prev_msg.get("content"))
            curr_blocks = _to_content_blocks(msg.get("content"))
            merged_blocks = prev_blocks + curr_blocks
            prev_msg["content"] = merged_blocks if merged_blocks else ""
        else:
            merged.append(dict(msg))

    return merged


def main():
    # Simulate Req 13 unmerged messages
    req13_messages = [
        {
            "role": "user",
            "content": "Final verification worker for completed Phase 1-2..."
        },
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Let me start by understanding..."},
                {"type": "tool_use", "id": "call_00_VCvAErR7TamhdeCaTXCs3579", "name": "bash", "input": {"command": "git status"}},
                {"type": "tool_use", "id": "call_01_1BeVw42vxSJxRPgDnf0x4842", "name": "bash", "input": {"command": "git diff"}}
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_00_VCvAErR7TamhdeCaTXCs3579", "content": "On branch spec/..."}
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_01_1BeVw42vxSJxRPgDnf0x4842", "content": " internal/refbackend/..."}
            ]
        }
    ]

    print("Before merging:")
    print(f"Messages count: {len(req13_messages)}")
    for i, m in enumerate(req13_messages):
        print(f"  [{i}] role={m['role']} blocks={len(_to_content_blocks(m['content']))}")

    merged = _merge_consecutive_anthropic_messages(req13_messages)

    print("\nAfter merging:")
    print(f"Messages count: {len(merged)}")
    for i, m in enumerate(merged):
        print(f"  [{i}] role={m['role']} blocks={len(_to_content_blocks(m['content']))}")
        for b_idx, b in enumerate(_to_content_blocks(m['content'])):
            print(f"      block[{b_idx}]: type={b.get('type')}, id/tool_use_id={b.get('id') or b.get('tool_use_id')}")

if __name__ == "__main__":
    main()
