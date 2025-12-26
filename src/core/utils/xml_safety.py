"""
XML safety utilities.

This module provides safe XML parsing functions to protect against common attacks
like XML bombs (Billion Laughs) and entity expansion.
"""

import logging
import xml.etree.ElementTree as ET  # noqa: N817

from src.core.common.exceptions import LLMProxyError

logger = logging.getLogger(__name__)


class XMLSafetyError(LLMProxyError):
    """Base error for XML safety issues."""


def safe_xml_parse(
    xml_data: str | bytes, max_size: int = 10 * 1024 * 1024
) -> ET.Element:
    """
    Safely parse XML data with protection against DoS attacks.

    Protects against:
    - XML bomb attacks (Billion Laughs) - exponential entity expansion
    - Deeply nested XML - stack overflow
    - Large XML content - memory exhaustion

    Args:
        xml_data: XML string or bytes to parse
        max_size: Maximum allowed size in bytes (default 10MB)

    Returns:
        Parsed XML element

    Raises:
        XMLSafetyError: If XML is unsafe or malformed
    """
    # Import sys inside function to avoid circular import issues
    import sys

    # Convert bytes to string if needed
    if isinstance(xml_data, bytes):
        try:
            xml_str = xml_data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise XMLSafetyError(
                f"XML data contains invalid UTF-8: {e!s}",
                details={"error": "invalid_encoding"},
            ) from e
    else:
        xml_str = xml_data

    # Check size limits (prevent memory exhaustion)
    if len(xml_str) > max_size:
        raise XMLSafetyError(
            f"XML data too large: {len(xml_str)} bytes (limit: {max_size} bytes)",
            details={
                "error": "xml_too_large",
                "actual_size": len(xml_str),
                "max_size": max_size,
            },
        )

    # Check for XML bomb patterns (entity expansion attacks)
    if "<!DOCTYPE" in xml_str and ("<!ENTITY" in xml_str):
        # Look for entity expansion patterns typical in XML bombs
        import re

        entity_pattern = r'<!ENTITY\s+\w+\s+"&\w+;'
        if re.search(entity_pattern, xml_str, re.IGNORECASE):
            raise XMLSafetyError(
                "XML contains potentially malicious entity expansion",
                details={"error": "xml_entity_expansion"},
            )

    # Limit nesting depth to prevent stack overflow
    max_depth = 100

    # Count nested tags to estimate depth
    open_tags = 0
    for char in xml_str:
        if char == "<":
            open_tags += 1
            if open_tags > max_depth:
                raise XMLSafetyError(
                    f"XML nesting depth exceeds limit: {open_tags} (limit: {max_depth})",
                    details={
                        "error": "xml_depth_exceeded",
                        "actual_depth": open_tags,
                        "max_depth": max_depth,
                    },
                )

    # Parse with safety measures
    try:
        original_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(min(max_depth * 2, original_limit))

        try:
            # Create safe parser (basic XMLParser without external entity support)
            parser = ET.XMLParser()

            root = ET.fromstring(xml_str, parser)
            return root

        finally:
            sys.setrecursionlimit(original_limit)

    except ET.ParseError as e:
        raise XMLSafetyError(
            f"XML parsing failed: {e!s}",
            details={"error": "xml_parse_error", "parse_error": str(e)},
        ) from e
    except RecursionError as e:
        raise XMLSafetyError(
            "XML nesting depth caused stack overflow",
            details={"error": "xml_stack_overflow"},
        ) from e
    except Exception as e:
        raise XMLSafetyError(
            f"Unexpected error parsing XML: {e!s}",
            details={"error": "xml_unexpected_error"},
        ) from e
