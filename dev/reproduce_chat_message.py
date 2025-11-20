
from src.core.domain.chat import ChatMessage

msg_data = {"role": "assistant", "content": "Hello", "reasoning": "I should say hello"}
msg = ChatMessage(**msg_data)
print(f"Reasoning content: {msg.reasoning_content}")

msg_data_2 = {"role": "assistant", "content": "Hello", "reasoning_details": "I should say hello"}
msg_2 = ChatMessage(**msg_data_2)
print(f"Reasoning content 2: {msg_2.reasoning_content}")

