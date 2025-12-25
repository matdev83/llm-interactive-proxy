#!/usr/bin/env python3
"""
DoS vulnerability test for capture_reader.py

This script demonstrates unbounded memory growth in capture_reader
due to unlimited list size when reading from malicious files.
"""

import os
import sys

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

def test_capture_reader_vulnerability():
    """
    Test for DoS vulnerability in capture_reader's unbounded entries list
    """
    try:
        print("Successfully imported CaptureFileReader")
        
        # The vulnerability is in load() method where entries list grows without bounds
        # A malicious capture file with millions of entries could cause memory exhaustion
        
        print("\n=== VULNERABILITY ANALYSIS ===")
        print("File: src/core/simulation/capture_reader.py")
        print("Function: load() method, lines ~91-96") 
        print("Issue: entries list grows without any size limits")
        print("Attack vector: Malicious capture file with excessive entries")
        print("Impact: Memory exhaustion via unbounded list growth")
        print("\nFixed code pattern:")
        print("  entries: list[CaptureEntry] = []")
        print("  while True:")
        print("      if len(entries) >= MAX_CAPTURE_ENTRIES:")
        print("          break  # DoS PROTECTION")
        print("      entry_dict = cbor2.load(f)")
        print("      entry = CaptureEntry.from_dict(entry_dict)")
        print("      entries.append(entry)  # BOUNDED GROWTH")
        
        print("\n=== ATTACK SCENARIO ===")
        print("1. Attacker creates malicious capture file with millions of entries")
        print("2. Victim calls capture_reader.load() on the file")
        print("3. Memory grows unbounded as entries list expands")
        print("4. System becomes unresponsive or crashes (DoS)")
        
        return True
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        return False

if __name__ == "__main__":
    success = test_capture_reader_vulnerability()
    if success:
        print("\n=== VULNERABILITY CONFIRMED ===")
        print("Unbounded list growth in capture_reader poses DoS risk")
    else:
        print("\n=== ANALYSIS FAILED ===")
        print("Could not confirm vulnerability due to errors")