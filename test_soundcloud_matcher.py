#!/usr/bin/env python3
"""Test script to verify SoundCloud matching improvements"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from lib.catalog.matcher import MatchIndex, _soundcloud_title_variations
from lib.text import normalize_key

def test_soundcloud_title_variations():
    """Test the SoundCloud title variations function"""
    print("Testing SoundCloud title variations...")

    # Test cases based on user examples
    test_cases = [
        "metropole & Anomalie",
        "swindail ballpoint 1 & Wu-zi",
        "well well prod enaur & on1y",
        "diversa underscore once again & a",
        "01 - Test Track",
        "Artist - Track Name",
        "Track Name (feat. Other)",
        "Simple Title"
    ]

    for title in test_cases:
        variations = _soundcloud_title_variations(title)
        print(f"  '{title}' -> {variations}")

    print()

def test_matcher_improvements():
    """Test that the matcher improvements work for SoundCloud-like data"""
    print("Testing matcher improvements...")

    # Create a mock catalog that simulates local files
    catalog = [
        {
            'path': r'Y:\music\crate\Anomalie - Métropole.flac',
            'artist': 'Anomalie',
            'album': 'Some Album',
            'title': 'Métropole',
            'track': 1,
            'length': 180.0
        },
        {
            'path': r'Y:\music\crate\Swindail - Ballpoint.mp3',
            'artist': 'Swindail',
            'album': 'Another Album',
            'title': 'Ballpoint',
            'track': 9,
            'length': 210.0
        },
        {
            'path': r'Y:\music\crate\on1y - well well.wav',
            'artist': 'on1y',
            'album': 'Yet Another Album',
            'title': 'well well',
            'track': 1,
            'length': 240.0
        },
        {
            'path': r'Y:\music\crate\DIVERSA - once again.aiff',
            'artist': 'DIVERSA',
            'album': 'Final Album',
            'title': 'once again',
            'track': 9,
            'length': 195.0
        }
    ]

    # Create the matcher index
    index = MatchIndex(catalog)

    # Test SoundCloud-like rows
    test_rows = [
        {
            'track_name': 'metropole',
            'artist_names': 'metropole & Anomalie',
            'album_name': 'Some Album',
            'duration_ms': 180000,  # 180 seconds
            'track_id': 'test1'
        },
        {
            'track_name': 'swindail ballpoint 1',
            'artist_names': 'swindail ballpoint 1 & Wu-zi',
            'album_name': 'Another Album',
            'duration_ms': 210000,  # 210 seconds
            'track_id': 'test2'
        },
        {
            'track_name': 'well well prod enaur',
            'artist_names': 'well well prod enaur & on1y',
            'album_name': 'Yet Another Album',
            'duration_ms': 240000,  # 240 seconds
            'track_id': 'test3'
        },
        {
            'track_name': 'diversa underscore once again',
            'artist_names': 'diversa underscore once again & a',
            'album_name': 'Final Album',
            'duration_ms': 195000,  # 195 seconds
            'track_id': 'test4'
        }
    ]

    # Test matching
    for i, row in enumerate(test_rows):
        print(f"\nTest row {i+1}:")
        print(f"  Title: {row['track_name']}")
        print(f"  Artist: {row['artist_names']}")

        entry, tier_number = index.match(row)
        if entry:
            print(f"  MATCHED: {entry['title']} by {entry['artist']} (tier {tier_number})")
            print(f"  Path: {entry['path']}")
        else:
            print(f"  UNMATCHED")

    print("\nDone.")

if __name__ == '__main__':
    test_soundcloud_title_variations()
    test_matcher_improvements()