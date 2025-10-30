"""
Mixin for shared Gemini Code Assist API logic.

This mixin contains the common logic for handling the Code Assist API,
including the fix for the 64K systemInstruction token limit.

BACKGROUND:
-----------
The Gemini Code Assist API has a hidden 64K token limit on the separate
`systemInstruction` field, independent from the model's 1M context window.

THE FIX (KiloCode's Approach):
-------------------------------
Instead of using the separate `systemInstruction` field (which has a 64K limit),
we prepend system messages as the FIRST user message in the `contents` array.
This allows system messages to use the model's full 1M context window.

REFERENCES:
-----------
- Original fix commit: de251c3f
- Regression tests: tests/unit/connectors/test_gemini_64k_systeminstruction_limit.py
- KiloCode implementation: dev/thrdparty/kilocode/src/api/providers/gemini-cli.ts:292-298
- Documentation: docs/gemini_code_assist_parameters.md
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GeminiCodeAssistMixin:
    """Shared logic for Gemini Code Assist API requests.

    This mixin provides methods for converting system messages and building
    Code Assist API requests. It implements the fix for the 64K systemInstruction
    token limit by using KiloCode's approach of prepending system messages as
    the first user message in the contents array.

    Usage:
        class MyGeminiConnector(GeminiBackend, GeminiCodeAssistMixin):
            # Connector-specific implementation
            pass
    """

    def _convert_system_messages_for_code_assist(
        self, gemini_request: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert system messages to KiloCode's approach (first user message).

        This method implements the fix for the 64K systemInstruction token limit
        by prepending system messages as the first user message in the contents array.

        The Code Assist API does not support 'system' role in the contents array,
        and the separate `systemInstruction` field has a 64K token limit. To work
        around this, we:
        1. Extract all system messages from the contents array
        2. Convert them to user role
        3. Prepend them as the FIRST message in the contents array

        This allows system messages to use the model's full 1M context window
        instead of being limited to 64K tokens.

        Args:
            gemini_request: Gemini-formatted request with potentially system role messages.
                           Expected structure: {"contents": [...], "generationConfig": {...}, ...}

        Returns:
            Final contents array with system messages converted to first user message.
            The returned list has system messages (if any) prepended as the first user
            message, followed by all other (non-system) messages in original order.

        Example:
            Input:
                {"contents": [
                    {"role": "system", "parts": [{"text": "You are helpful"}]},
                    {"role": "user", "parts": [{"text": "Hello"}]},
                    {"role": "model", "parts": [{"text": "Hi!"}]}
                ]}

            Output:
                [
                    {"role": "user", "parts": [{"text": "You are helpful"}]},  # System as user
                    {"role": "user", "parts": [{"text": "Hello"}]},
                    {"role": "model", "parts": [{"text": "Hi!"}]}
                ]
        """
        # Code Assist API doesn't support 'system' role in contents array
        # KiloCode's approach: Put system messages as FIRST user message in contents
        # This avoids the 64K token limit on the separate systemInstruction field
        system_instruction_parts: list[dict[str, Any]] = []
        filtered_contents: list[dict[str, Any]] = []

        for content in gemini_request.get("contents", []):
            if content.get("role") == "system":
                # Collect all system message parts
                parts = content.get("parts", [])
                if isinstance(parts, list):
                    system_instruction_parts.extend(parts)
                elif parts:
                    system_instruction_parts.append(parts)
            else:
                filtered_contents.append(content)

        # Prepend system messages as first user message (KiloCode's approach)
        # This avoids hitting the 64K limit on systemInstruction field
        final_contents: list[dict[str, Any]] = []
        if system_instruction_parts:
            final_contents.append(
                {
                    "role": "user",
                    "parts": system_instruction_parts,
                }
            )
        final_contents.extend(filtered_contents)

        return final_contents

    def _build_code_assist_request(
        self, gemini_request: dict[str, Any], final_contents: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build Code Assist API request structure.

        This method builds the request dictionary for the Code Assist API,
        including the contents array, generation config, and optional fields
        like tools, toolConfig, and safetySettings.

        Args:
            gemini_request: Original Gemini-formatted request with all fields
            final_contents: Processed contents array (with system messages converted)

        Returns:
            Code Assist API request dict with structure:
            {
                "contents": [...],
                "generationConfig": {...},
                "tools": [...],           # Optional
                "toolConfig": {...},      # Optional
                "safetySettings": [...]   # Optional
            }
        """
        # Build the request for Code Assist API
        code_assist_request: dict[str, Any] = {
            "contents": final_contents,
            "generationConfig": gemini_request.get("generationConfig", {}),
        }

        # Add other fields if present
        if "tools" in gemini_request:
            code_assist_request["tools"] = gemini_request["tools"]
        if "toolConfig" in gemini_request:
            code_assist_request["toolConfig"] = gemini_request["toolConfig"]
        if "safetySettings" in gemini_request:
            code_assist_request["safetySettings"] = gemini_request["safetySettings"]

        return code_assist_request
