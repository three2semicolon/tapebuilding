#!/usr/bin/env python3
"""Debug script to check normalization functions"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from lib.text import normalize_key, group_key, normalize_title

def test_normalization():
    """Test normalization functions with accented characters"""
    test_strings = [
        "metropole",
        "Métropole",
        "metropole & Anomalie",
        "Métropole & Anomalie"
    ]

    for s in test_strings:
        nk = normalize_key(s)
        gk = group_key(s)
        nt = normalize_title(s)
        print(f"'{s}':")
        print(f"  normalize_key:  '{nk}'")
        print(f"  group_key:      '{gk}'")
        print(f"  normalize_title:'{nt}'")
        print()

if __name__ == '__main__':
    test_normalization()