"""Regression test for XML Bomb DoS vulnerability fix in SSO Service.

This test verifies that safe_xml_parse properly rejects XML bombs and other
DoS attack vectors to prevent exponential memory growth and CPU exhaustion.

Fixed: safe_xml_parse() function added protections against:
- XML bomb attacks (Billion Laughs) - exponential entity expansion
- Deeply nested XML - stack overflow
- Large XML content - memory exhaustion
"""

import pytest
from src.core.auth.sso.exceptions import AuthenticationError
from src.core.auth.sso.sso_service import safe_xml_parse


class TestXMLBombDoSRegression:
    """Regression tests for XML Bomb DoS vulnerability fix."""

    def create_xml_bomb(self) -> str:
        """Create an XML bomb with exponential entity expansion."""
        return """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<lolz>&lol4;</lolz>"""

    def create_nested_xml_bomb(self, depth: int = 100) -> str:
        """Create a deeply nested XML bomb."""
        nested_bomb = '<?xml version="1.0"?>\n'
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

    def test_classic_xml_bomb_rejected(self) -> None:
        """Test that classic XML bomb (Billion Laughs attack) is rejected."""
        xml_bomb = self.create_xml_bomb()

        with pytest.raises(AuthenticationError) as exc_info:
            safe_xml_parse(xml_bomb)

        assert exc_info.value.details.get("error") == "xml_entity_expansion"

    def test_nested_xml_bomb_rejected(self) -> None:
        """Test that deeply nested XML bombs are rejected."""
        # Test with depth that should trigger entity expansion detection
        nested_bomb = self.create_nested_xml_bomb(100)

        with pytest.raises(AuthenticationError) as exc_info:
            safe_xml_parse(nested_bomb)

        # Should be rejected either for entity expansion or depth
        error_type = exc_info.value.details.get("error")
        assert error_type in ("xml_entity_expansion", "xml_depth_exceeded")

    def test_large_xml_rejected(self) -> None:
        """Test that very large XML content is rejected."""
        # Create XML with large content (>10MB)
        large_xml = '<?xml version="1.0"?><root>'
        large_xml += "A" * (11 * 1024 * 1024)  # 11MB > 10MB limit
        large_xml += "</root>"

        with pytest.raises(AuthenticationError) as exc_info:
            safe_xml_parse(large_xml)

        assert exc_info.value.details.get("error") == "xml_too_large"
        assert exc_info.value.details.get("actual_size") > 10 * 1024 * 1024

    def test_deeply_nested_xml_rejected(self) -> None:
        """Test that deeply nested XML (without entities) is rejected."""
        # Create deeply nested XML without entities
        nested_xml = "<root>"
        for _ in range(101):  # Exceeds max_depth of 100
            nested_xml += "<nested>"
        nested_xml += "content"
        for _ in range(101):
            nested_xml += "</nested>"
        nested_xml += "</root>"

        with pytest.raises(AuthenticationError) as exc_info:
            safe_xml_parse(nested_xml)

        assert exc_info.value.details.get("error") == "xml_depth_exceeded"
        assert exc_info.value.details.get("actual_depth") > 100

    def test_normal_xml_works(self) -> None:
        """Test that normal XML is parsed successfully."""
        normal_xml = '<?xml version="1.0"?><root><child>content</child></root>'

        result = safe_xml_parse(normal_xml)

        assert result is not None
        assert result.tag == "root"

    def test_saml_metadata_xml_works(self) -> None:
        """Test that legitimate SAML metadata XML is parsed successfully."""
        saml_xml = """<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" entityID="test">
  <IDPSSODescriptor>
    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://test.com/sso"/>
  </IDPSSODescriptor>
</EntityDescriptor>"""

        result = safe_xml_parse(saml_xml)

        assert result is not None
        assert result.tag == "{urn:oasis:names:tc:SAML:2.0:metadata}EntityDescriptor"
