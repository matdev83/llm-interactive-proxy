import logging
from typing import Any

from src.core.domain.chat import ChatMessage as Message


class Role:
    ASSISTANT = "assistant"
    SYSTEM = "system"


from src.core.config.app_config import AppConfig
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.core.services.dangerous_command_service import DangerousCommandService

logger = logging.getLogger(__name__)


class DangerousCommandMiddleware(IResponseMiddleware):
    def __init__(
        self, dangerous_command_service: DangerousCommandService, app_config: AppConfig
    ):
        self.dangerous_command_service = dangerous_command_service
        self.app_config = app_config

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        if not self.app_config.session.dangerous_command_prevention_enabled:
            return response

        if isinstance(response, list):
            processed_messages = []
            for message in response:
                if isinstance(message, Message) and message.tool_calls:
                    safe_tool_calls = []
                    for tool_call in message.tool_calls:
                        scan_result = self.dangerous_command_service.scan_tool_call(
                            tool_call
                        )
                        if scan_result:
                            rule, command = scan_result
                            logger.warning(
                                f"Intercepted a potentially dangerous command. "
                                f"Rule: {rule.name}, Command: '{command}'"
                            )
                            # Create a new message to send to the LLM
                            error_message = Message(
                                role=Role.SYSTEM,
                                content=(
                                    "This is llm-interactive-proxy security enforcement "
                                    "module working on behalf user in charge. Your latest "
                                    "tool call has been intercepted and not forwarded to "
                                    "the agent. You were trying to execute a potentially "
                                    "dangerous command. This proxy won't pass any further "
                                    "potentially harmful tool calls to the agent, so don't "
                                    "try to repeat the latest call. Your only option if you "
                                    "want given command to be executed is to inform user "
                                    "that he needs to execute such command on he's own. "
                                    "You must also warn the user about potential "
                                    "destructive consequences of running of such command. "
                                    "Such information WILL get passed back to the user"
                                ),
                            )
                            processed_messages.append(error_message)
                        else:
                            safe_tool_calls.append(tool_call)

                    # Reconstruct the message with only the safe tool calls
                    if safe_tool_calls:
                        message.tool_calls = safe_tool_calls
                        processed_messages.append(message)

                else:
                    processed_messages.append(message)

            return processed_messages

        return response
