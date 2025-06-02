import logging
import re
from typing import Optional, Tuple, List, Dict, Any
from models import ChatMessage, MessageContentPartText # Import necessary Pydantic models

logger = logging.getLogger(__name__)

class ProxyState:
    def __init__(self):
        self.override_model: Optional[str] = None

    def set_override_model(self, model_name: str):
        logger.info(f"Setting override model to: {model_name}")
        self.override_model = model_name

    def unset_override_model(self):
        logger.info("Unsetting override model.")
        self.override_model = None

    def get_effective_model(self, requested_model: str) -> str:
        if self.override_model:
            logger.info(f"Overriding requested model '{requested_model}' with '{self.override_model}'")
            return self.override_model
        return requested_model

proxy_state = ProxyState() # Global instance for simplicity

# Command regex: !/command(arg1=val1, arg2=val2, ...)
COMMAND_PATTERN = re.compile(r"!/(\w+)\(([^)]*)\)") # Allows empty args
ARG_PATTERN = re.compile(r"(\w+)=([^,]+(?:,\s*\w+=[^,]+)*)") # Parses key=value, allows model names with '/'

def parse_arguments(args_str: str) -> Dict[str, str]:
    args = {}
    if not args_str.strip(): # Handle empty arguments string like in !/unset(model)
        return args
    # Simpler parsing for "key=value" format, assuming no commas in value for now
    # For model names like "foo/bar-baz", this is fine.
    # If values could contain commas, a more robust parser is needed.
    for part in args_str.split(','):
        if '=' in part:
            key, value = part.split('=', 1)
            args[key.strip()] = value.strip()
        else: # For commands like !/unset(model) where 'model' isn't a value but a key itself.
            args[part.strip()] = True # Treat as a flag
    return args

def _process_text_for_commands(text_content: str) -> Tuple[str, bool]:
    """
    Helper to process commands within a single text string.
    Returns the modified text and a boolean indicating if commands were found.
    """
    remaining_text = text_content
    commands_found_in_text = False
    
    # Use finditer to handle multiple commands in the same text block
    processed_text_parts = []
    last_slice_end = 0

    for match in COMMAND_PATTERN.finditer(text_content):
        commands_found_in_text = True
        command_full_match = match.group(0)
        command_name = match.group(1).lower()
        args_str = match.group(2)
        args = parse_arguments(args_str)
        
        # Add text before this command
        processed_text_parts.append(text_content[last_slice_end:match.start()])
        last_slice_end = match.end()

        logger.info(f"Found command: '{command_full_match}' -> name='{command_name}', args={args}")
        
        if command_name == "set":
            if "model" in args and isinstance(args["model"], str):
                proxy_state.set_override_model(args["model"])
            else:
                logger.warning("!/set command found without valid 'model=model_name' argument.")
        elif command_name == "unset":
            # !/unset(model) implies unsetting the model override
            if "model" in args: # Check if 'model' is mentioned as a key
                proxy_state.unset_override_model()
            else:
                logger.warning("!/unset command should be like !/unset(model).")
        else:
            logger.warning(f"Unknown command: {command_name}. Keeping command text.")
            # If unknown, keep the command text by adding it back
            processed_text_parts.append(command_full_match)
            
    # Add any remaining text after the last command
    processed_text_parts.append(text_content[last_slice_end:])
    
    final_text = "".join(processed_text_parts).strip()
    return final_text, commands_found_in_text


def process_commands_in_messages(messages: List[ChatMessage]) -> Tuple[List[ChatMessage], bool]:
    """
    Processes commands in messages. Checks the last message first.
    Returns the (potentially) modified messages list and a boolean indicating if any command was processed.
    Modifies messages in place if they are Pydantic models, or returns a new list of dicts.
    For safety with Pydantic, it's better to return new, modified model instances.
    """
    if not messages:
        return messages, False

    modified_messages = [msg.model_copy(deep=True) for msg in messages]
    any_command_processed_overall = False

    # Iterate backwards to find the last message suitable for command processing
    # (typically the last user message, but we check content type)
    for i in range(len(modified_messages) - 1, -1, -1):
        msg = modified_messages[i]
        content_modified_for_this_message = False
        
        if isinstance(msg.content, str):
            processed_text, commands_found = _process_text_for_commands(msg.content)
            if commands_found:
                msg.content = processed_text
                any_command_processed_overall = True
                content_modified_for_this_message = True
        elif isinstance(msg.content, list): # Multimodal
            new_content_parts = []
            part_level_command_found = False
            for part in msg.content:
                if part.type == "text":
                    processed_text, commands_found = _process_text_for_commands(part.text)
                    if commands_found:
                        part_level_command_found = True
                        any_command_processed_overall = True
                    # Add text part only if it's not empty after stripping commands
                    if processed_text.strip():
                         new_content_parts.append(MessageContentPartText(type="text", text=processed_text))
                    elif not commands_found : # if not command found and it was empty already preserve it
                        new_content_parts.append(MessageContentPartText(type="text", text=processed_text))
                else:
                    new_content_parts.append(part.model_copy(deep=True)) # Pass through non-text parts

            if part_level_command_found:
                msg.content = new_content_parts
                content_modified_for_this_message = True
        
        # If commands were processed in this message, we usually assume this is the intended command-bearing message
        # and stop further backward searching for commands in prior messages for this request.
        if content_modified_for_this_message:
            logger.info(f"Commands processed in message index {i} (from end). New content: '{msg.content}'")
            break 

    # Filter out messages that became entirely empty (e.g. multimodal list became empty)
    final_messages = []
    for msg in modified_messages:
        if isinstance(msg.content, list) and not msg.content:
            logger.info(f"Removing message (role: {msg.role}) as its multimodal content became empty after command processing.")
            continue
        # Do not remove messages with empty string content: {"role":"user", "content":""} is valid.
        final_messages.append(msg)
    
    if not final_messages and any_command_processed_overall and messages:
        logger.info("All messages were removed after command processing. This might indicate a command-only request.")

    return final_messages, any_command_processed_overall