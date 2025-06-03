import logging
import re
from typing import Optional, Tuple, List, Dict, Any
from models import ChatMessage, MessageContentPartText # Import necessary Pydantic models

logger = logging.getLogger(__name__)

class ProxyState:
    """Manages the state of the proxy, particularly model overrides."""
    def __init__(self):
        """Initializes ProxyState with no model override."""
        self.override_model: Optional[str] = None

    def set_override_model(self, model_name: str):
        """Sets a model name to override subsequent requests."""
        logger.info(f"Setting override model to: {model_name}")
        self.override_model = model_name

    def unset_override_model(self):
        """Clears any existing model override."""
        logger.info("Unsetting override model.")
        self.override_model = None

    def get_effective_model(self, requested_model: str) -> str:
        """
        Determines the effective model to be used, considering any override.

        Args:
            requested_model: The model originally requested by the client.

        Returns:
            The overridden model name if an override is set, otherwise the requested_model.
        """
        if self.override_model:
            logger.info(f"Overriding requested model '{requested_model}' with '{self.override_model}'")
            return self.override_model
        return requested_model

proxy_state = ProxyState() # Global instance for simplicity

# Command regex: !/command(arg1=val1, arg2=val2, ...)
COMMAND_PATTERN = re.compile(r"!/(\w+)\(([^)]*)\)") # Allows empty args
ARG_PATTERN = re.compile(r"(\w+)=([^,]+(?:,\s*\w+=[^,]+)*)") # Parses key=value, allows model names with '/'

def parse_arguments(args_str: str) -> Dict[str, Any]:
    """
    Parses a string of arguments into a dictionary.

    The argument string is expected to be a comma-separated list of key-value pairs
    (e.g., "model=gpt-4, temperature=0.7") or standalone keys (e.g., "debug_mode").
    Standalone keys are treated as flags and assigned a boolean True value.

    Args:
        args_str: The string containing arguments.

    Returns:
        A dictionary where keys are argument names and values are their parsed values
        (strings for key-value pairs, True for flags).
    """
    logger.debug(f"Parsing arguments from string: '{args_str}'")
    args = {}
    if not args_str.strip(): # Handle empty arguments string like in !/unset(model)
        logger.debug("Argument string is empty, returning empty dict.")
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
    logger.debug(f"Parsed arguments: {args}")
    return args

def _process_text_for_commands(text_content: str) -> Tuple[str, bool]:
    """
    Helper to process commands within a single text string.
    Returns the modified text and a boolean indicating if commands were found.
    """
    logger.debug(f"Processing text for commands: '{text_content}'")
    commands_found_in_text = False

    processed_text_parts = []
    last_slice_end = 0

    for match in COMMAND_PATTERN.finditer(text_content):
        commands_found_in_text = True
        command_full_match = match.group(0)
        command_name_extracted = match.group(1)
        args_str_extracted = match.group(2)
        logger.debug(f"Regex match: Full='{command_full_match}', Command='{command_name_extracted}', ArgsStr='{args_str_extracted}'")

        command_name = command_name_extracted.lower()
        args = parse_arguments(args_str_extracted) # parse_arguments now has its own DEBUG logs

        processed_text_parts.append(text_content[last_slice_end:match.start()])
        last_slice_end = match.end()

        logger.info(f"Processing command: name='{command_name}', args={args}")
        logger.info(f"State before command '{command_name}': override_model='{proxy_state.override_model}'")

        if command_name == "set":
            if "model" in args and isinstance(args["model"], str):
                proxy_state.set_override_model(args["model"])
            else:
                logger.warning("!/set command found without valid 'model=model_name' argument. No change to override model.")
        elif command_name == "unset":
            if "model" in args:
                proxy_state.unset_override_model()
            else:
                logger.warning("!/unset command should be like !/unset(model). No change to override model.")
        else:
            logger.warning(f"Unknown command: {command_name}. Keeping command text.")
            processed_text_parts.append(command_full_match)

        logger.info(f"State after command '{command_name}': override_model='{proxy_state.override_model}'")

    processed_text_parts.append(text_content[last_slice_end:])

    final_text = "".join(processed_text_parts).strip()
    logger.debug(f"Text after command processing: '{final_text}'")
    return final_text, commands_found_in_text


def process_commands_in_messages(messages: List[ChatMessage]) -> Tuple[List[ChatMessage], bool]:
    """
    Processes commands in messages. Checks the last message first.
    Returns the (potentially) modified messages list and a boolean indicating if any command was processed.
    Modifies messages in place if they are Pydantic models, or returns a new list of dicts.
    For safety with Pydantic, it's better to return new, modified model instances.
    """
    if not messages:
        logger.debug("process_commands_in_messages received empty messages list.")
        return messages, False
    logger.debug(f"Processing messages for commands. Initial message count: {len(messages)}")

    modified_messages = [msg.model_copy(deep=True) for msg in messages]
    any_command_processed_overall = False

    # Iterate backwards to find the last message suitable for command processing
    # (typically the last user message, but we check content type)
    for i in range(len(modified_messages) - 1, -1, -1):
        msg = modified_messages[i]
        content_modified_for_this_message = False

        if isinstance(msg.content, str):
            logger.debug(f"Processing message index {i} (from end), current content (str): '{msg.content}'")
            processed_text, commands_found = _process_text_for_commands(msg.content)
            if commands_found:
                msg.content = processed_text
                any_command_processed_overall = True
                content_modified_for_this_message = True
        elif isinstance(msg.content, list): # Multimodal
            logger.debug(f"Processing message index {i} (from end), current content (list of parts). Part count: {len(msg.content)}")
            new_content_parts = []
            part_level_command_found = False
            for part_idx, part in enumerate(msg.content):
                if part.type == "text":
                    logger.debug(f"Processing text part index {part_idx} in message {i}: '{part.text}'")
                    processed_text, commands_found = _process_text_for_commands(part.text)
                    if commands_found: # Corrected typo here
                        part_level_command_found = True
                        any_command_processed_overall = True
                    # Add text part only if it's not empty after stripping commands
                    if processed_text.strip():
                         new_content_parts.append(MessageContentPartText(type="text", text=processed_text))
                    elif not commands_found : # if not command found and it was empty already preserve it
                        new_content_parts.append(MessageContentPartText(type="text", text=processed_text))
                    else:
                        logger.debug(f"Text part became empty after command processing and was removed: Original '{part.text}'")
                else:
                    new_content_parts.append(part.model_copy(deep=True)) # Pass through non-text parts

            if part_level_command_found:
                msg.content = new_content_parts
                content_modified_for_this_message = True

        # If commands were processed in this message, we usually assume this is the intended command-bearing message
        # and stop further backward searching for commands in prior messages for this request.
        if content_modified_for_this_message:
            logger.info(f"Commands processed in message index {i} (from end). Role: {msg.role}. New content: '{msg.content}'")
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

    logger.debug(f"Finished processing messages. Final message count: {len(final_messages)}. Commands processed overall: {any_command_processed_overall}")
    return final_messages, any_command_processed_overall
