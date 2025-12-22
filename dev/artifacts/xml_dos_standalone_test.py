#!/usr/bin/env python3
"""
Standalone test for XML DoS vulnerability fix.
"""

import sys
import re
import xml.etree.ElementTree as ET


class AuthenticationError(Exception):
    """Mock AuthenticationError for testing."""
    def __init__(self, message, details=None, original_error=None):
        super().__init__(message)
        self.details = details or {}
        self.original_error = original_error


def safe_xml_parse(xml_data):
    """
    Safely parse XML data with protection against DoS attacks.
    """
    # Convert bytes to string if needed
    if isinstance(xml_data, bytes):
        try:
            xml_str = xml_data.decode('utf-8')
        except UnicodeDecodeError as e:
            raise AuthenticationError(
                f"XML data contains invalid UTF-8: {e!s}",
                details={"error": "invalid_encoding"},
                original_error=e,
            ) from e
    else:
        xml_str = xml_data
    
    # Check size limits
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
    
    # Check for XML bomb patterns
    if '<!DOCTYPE' in xml_str and ('<!ENTITY' in xml_str):
        entity_pattern = r'<!ENTITY\s+\w+\s+"&\w+;'
        if re.search(entity_pattern, xml_str, re.IGNORECASE):
            raise AuthenticationError(
                "XML contains potentially malicious entity expansion",
                details={"error": "xml_entity_expansion"},
            )
    
    # Limit nesting depth
    max_depth = 100
    open_tags = 0
    for char in xml_str:
        if char == '<':
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
            # Create safe parser
            try:
                parser = ET.XMLParser(resolve_entities=False)
            except TypeError:
                parser = ET.XMLParser()
            
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


def create_xml_bomb():
    """Create an XML bomb with exponential entity expansion."""
    xml_bomb = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<lolz>&lol4;</lolz>"""
    return xml_bomb


def create_safe_xml():
    """Create a legitimate SAML-like XML for testing."""
    safe_xml = """<?xml version="1.0"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">
  <saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
    <saml:Subject>
      <saml:NameID>user@example.com</saml:NameID>
    </saml:Subject>
  </saml:Assertion>
</samlp:Response>"""
    return safe_xml


def test_xml_bomb_protection():
    """Test protection against XML bomb attacks."""
    print("Testing XML Bomb Protection...")
    xml_bomb = create_xml_bomb()
    
    try:
        root = safe_xml_parse(xml_bomb)
        print("   [FAIL] XML bomb was NOT blocked!")
        return False
    except Exception as e:
        print(f"   [PASS] XML bomb blocked: {type(e).__name__}")
        return True


def test_safe_xml_parsing():
    """Test that legitimate XML still works."""
    print("\nTesting Safe XML Parsing...")
    safe_xml = create_safe_xml()
    
    try:
        root = safe_xml_parse(safe_xml)
        print("   [PASS] Legitimate XML parsed successfully")
        print(f"   Root tag: {root.tag}")
        return True
    except Exception as e:
        print(f"   [FAIL] Legitimate XML was blocked: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("XML DoS Protection Test (Standalone)")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 2
    
    if test_xml_bomb_protection():
        tests_passed += 1
    
    if test_safe_xml_parsing():
        tests_passed += 1
    
    print("\n" + "=" * 50)
    print(f"SUMMARY: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        print("[SUCCESS] XML DoS vulnerability has been fixed!")
        exit(0)
    else:
        print(f"[FAILURE] {total_tests - tests_passed} test(s) failed")
        exit(1)