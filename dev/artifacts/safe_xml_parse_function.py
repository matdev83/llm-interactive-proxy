def safe_xml_parse(xml_data: str | bytes) -> ET.Element:
    """
    Safely parse XML data with protection against DoS attacks.

    Protects against:
    - XML bomb attacks (Billion Laughs) - exponential entity expansion
    - Deeply nested XML - stack overflow
    - Large XML content - memory exhaustion

    Args:
        xml_data: XML string or bytes to parse

    Returns:
        Parsed XML element

    Raises:
        AuthenticationError: If XML is unsafe or malformed
    """
    # Convert bytes to string if needed
    if isinstance(xml_data, bytes):
        try:
            xml_str = xml_data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AuthenticationError(
                f"XML data contains invalid UTF-8: {e!s}",
                details={"error": "invalid_encoding"},
                original_error=e,
            ) from e
    else:
        xml_str = xml_data

    # Check size limits (prevent memory exhaustion)
    MAX_XML_SIZE = 10 * 1024 * 1024  # 10MB
    if len(xml_str) > MAX_XML_SIZE:
        raise AuthenticationError(
            f"XML data too large: {len(xml_str)} bytes (limit: {MAX_XML_SIZE} bytes)",
            details={
                "error": "xml_too_large",
                "actual_size": len(xml_str),
                "max_size": MAX_XML_SIZE,
            },
        )

    # Check for XML bomb patterns (entity expansion attacks)
    if "<!DOCTYPE" in xml_str and ("<!ENTITY" in xml_str):
        # Look for entity expansion patterns typical in XML bombs
        import re

        entity_pattern = r'<!ENTITY\s+\w+\s+"&\w+;'
        if re.search(entity_pattern, xml_str, re.IGNORECASE):
            raise AuthenticationError(
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
                raise AuthenticationError(
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
            # Create safe parser (disable external entities if supported)
            try:
                parser = ET.XMLParser(resolve_entities=False)  # Python 3.8+
            except (TypeError, AttributeError):
                parser = ET.XMLParser()  # Fallback for older versions

            root = ET.fromstring(xml_str, parser)
            return root

        finally:
            sys.setrecursionlimit(original_limit)

    except ET.ParseError as e:
        raise AuthenticationError(
            f"XML parsing failed: {e!s}",
            details={"error": "xml_parse_error", "parse_error": str(e)},
            original_error=e,
        ) from e
    except RecursionError as e:
        raise AuthenticationError(
            "XML nesting depth caused stack overflow",
            details={"error": "xml_stack_overflow"},
            original_error=e,
        ) from e
    except Exception as e:
        raise AuthenticationError(
            f"Unexpected error parsing XML: {e!s}",
            details={"error": "xml_unexpected_error"},
            original_error=e,
        ) from e
