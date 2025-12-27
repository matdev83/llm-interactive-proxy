"""
Quick test to see if the monkeypatch is working correctly in the test.
"""
import os
import tempfile
from pathlib import Path


def test_monkeypatch_approach():
    """Test if monkeypatching Path.read_text works as expected."""
    # Create a temp file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("test content")
        temp_file = f.name
    
    try:
        # Try reading normally
        p = Path(temp_file)
        print(f"Normal read: {p.read_text()}")
        
        # Monkeypatch Path.read_text
        original_read_text = Path.read_text
        
        def mock_read_text(self, *args, **kwargs):
            raise OSError("Permission denied")
        
        Path.read_text = mock_read_text
        
        # Try reading with monkeypatch
        try:
            content = p.read_text()
            print(f"After monkeypatch: {content}")
        except OSError as e:
            print(f"Caught OSError as expected: {e}")
        
        # Restore
        Path.read_text = original_read_text
        
        # Try reading again
        print(f"After restore: {p.read_text()}")
        
    finally:
        os.unlink(temp_file)


if __name__ == "__main__":
    test_monkeypatch_approach()
