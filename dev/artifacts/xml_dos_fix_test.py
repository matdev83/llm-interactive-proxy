#!/usr/bin/env python3
"""
Test script to verify XML DoS vulnerability fix in SSO Service.

This script tests the safe_xml_parse function to ensure it properly
defends against various XML-based DoS attacks.
"""

import os
import sys

# Add src to path so we can import the fixed module
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

try:
    from src.core.auth.sso.sso_service import safe_xml_parse
except ImportError as e:
    print(f"Failed to import safe_xml_parse: {e}")
    print("Make sure fix has been applied to sso_service.py")
    sys.exit(1)

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

def create_nested_xml_bomb(depth=100):
    """Create a deeply nested XML bomb."""
    nested_bomb = "<?xml version=\"1.0\"?>\n"
    nested_bomb += "<!DOCTYPE root [\n"
    
    # Create deeply nested entities
    for i in range(depth):
        if i == 0:
            nested_bomb += f"  <!ENTITY level{i} 'data'>\n"
        else:
            nested_bomb += f"  <!ENTITY level{i} '&level{i-1};&level{i-1};'>\n"
    
    nested_bomb += "]>\n"
    nested_bomb += f"<root>&level{depth-1};</root>"
    return nested_bomb

def create_large_xml():
    """Create very large XML content."""
    large_xml = "<?xml version=\"1.0\"?><root>"
    large_xml += "A" * 10_000_000  # 10MB of 'A' characters
    large_xml += "</root>"
    return large_xml

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

def test_nested_xml_protection():
    """Test protection against deeply nested XML."""
    print("\nTesting Nested XML Protection...")
    
    for depth in [10, 50, 150]:  # Test beyond the limit
        nested_bomb = create_nested_xml_bomb(depth)
        
        try:
            root = safe_xml_parse(nested_bomb)
            print(f"   [FAIL] Nested XML (depth {depth}) was NOT blocked!")
            return False
        except Exception as e:
            print(f"   [PASS] Nested XML (depth {depth}) blocked: {type(e).__name__}")
    
    return True

def test_large_xml_protection():
    """Test protection against large XML content."""
    print("\nTesting Large XML Protection...")
    large_xml = create_large_xml()
    
    try:
        root = safe_xml_parse(large_xml)
        print("   [FAIL] Large XML was NOT blocked!")
        return False
    except Exception as e:
        print(f"   [PASS] Large XML blocked: {type(e).__name__}")
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

def test_edge_cases():
    """Test edge cases."""
    print("\nTesting Edge Cases...")
    
    # Test empty string
    try:
        safe_xml_parse("")
        print("   [FAIL] Empty string should be rejected!")
        return False
    except Exception:
        print("   [PASS] Empty string correctly rejected")
    
    # Test malformed XML
    try:
        safe_xml_parse("<root><unclosed>")
        print("   [FAIL] Malformed XML should be rejected!")
        return False
    except Exception:
        print("   [PASS] Malformed XML correctly rejected")
    
    # Test non-UTF-8 bytes
    try:
        safe_xml_parse(b'\xff\xfe\x00\x00<root></root>')  # UTF-16 with BOM
        print("   [FAIL] Non-UTF-8 should be rejected!")
        return False
    except Exception:
        print("   [PASS] Non-UTF-8 correctly rejected")
    
    return True

if __name__ == "__main__":
    print("XML DoS Protection Test")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 5
    
    if test_xml_bomb_protection():
        tests_passed += 1
    
    if test_nested_xml_protection():
        tests_passed += 1
    
    if test_large_xml_protection():
        tests_passed += 1
    
    if test_safe_xml_parsing():
        tests_passed += 1
    
    if test_edge_cases():
        tests_passed += 1
    
    print("\n" + "=" * 50)
    print(f"SUMMARY: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        print("[SUCCESS] All XML DoS vulnerabilities have been fixed!")
        print("The SSO service is now protected against:")
        print("- XML bomb attacks (Billion Laughs)")
        print("- Deeply nested XML attacks")
        print("- Large XML content attacks")
        print("- Malformed XML")
        print("- Invalid encoding")
        exit(0)
    else:
        print(f"[FAILURE] {total_tests - tests_passed} test(s) failed")
        print("The fix may be incomplete or incorrect.")
        exit(1)