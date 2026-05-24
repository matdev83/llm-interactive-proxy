from src.core.domain.chat import ChatMessage, MessageContentPartText
from src.core.utils.token_count import extract_prompt_text


def test_extract_prompt_text_with_dict_messages():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    expected = "system: You are a helpful assistant.\nuser: Hello!"
    assert extract_prompt_text(messages) == expected


def test_extract_prompt_text_with_object_messages():
    messages = [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(role="user", content="Hello!"),
    ]
    expected = "system: You are a helpful assistant.\nuser: Hello!"
    assert extract_prompt_text(messages) == expected


def test_extract_prompt_text_with_reasoning_content():
    # Test reasoning_content in dict
    messages_dict = [
        {
            "role": "assistant",
            "reasoning_content": "I should say hello.",
            "content": "Hi!",
        }
    ]
    assert "assistant (reasoning): I should say hello." in extract_prompt_text(
        messages_dict
    )
    assert "assistant: Hi!" in extract_prompt_text(messages_dict)

    # Test reasoning_content in object
    messages_obj = [
        ChatMessage(
            role="assistant", reasoning_content="Logic here", content="Result here"
        )
    ]
    assert "assistant (reasoning): Logic here" in extract_prompt_text(messages_obj)
    assert "assistant: Result here" in extract_prompt_text(messages_obj)


def test_extract_prompt_text_with_multipart_content():
    # Multipart in dict
    messages_multipart = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this image?"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,..."},
                },
            ],
        }
    ]
    assert "user: What is in this image?" in extract_prompt_text(messages_multipart)
    # Ensure image part doesn't crash it and isn't included as text
    assert "image_url" not in extract_prompt_text(messages_multipart)

    # Multipart in objects
    messages_obj = [
        ChatMessage(
            role="user",
            content=[
                MessageContentPartText(type="text", text="Hello with object parts")
            ],
        )
    ]
    assert "user: Hello with object parts" in extract_prompt_text(messages_obj)


def test_extract_prompt_text_fallback():
    # Test that it doesn't return empty for unknown formats if possible
    # Passing something weird
    weird_messages = [{"role": "user", "something_else": "here"}]
    # It should fallback to str(messages) because result would be empty
    result = extract_prompt_text(weird_messages)
    assert "something_else" in result
    assert "here" in result


def test_extract_prompt_text_empty():
    assert extract_prompt_text([]) == ""
    assert extract_prompt_text(None) == ""
