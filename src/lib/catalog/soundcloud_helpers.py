"""lib.catalog.soundcloud_helpers - SoundCloud-specific helper functions.

Extracted from matcher.py to reduce file size and improve organization.
"""

import re

from lib.text import normalize_key


def _soundcloud_title_variations(title):
    """Generate title variations that might match SoundCloud metadata to local filenames.

    For SoundCloud, filenames often contain:
    - Track number prefixes: "01 - Track Name"
    - Artist prefixes: "Artist - Track Name"
    - Additional descriptive text

    This function tries to normalize and extract the core title.
    """
    if not title:
        return [title]

    variations = []
    title_lower = title.lower()

    # Original title
    variations.append(title)

    # Remove common track number prefixes (e.g., "01 - ", "001 - ")
    # Match digits followed by optional spaces, dash, optional spaces
    no_track_prefix = re.sub(r'^\s*\d+\s*[-–—]\s*', '', title)
    if no_track_prefix != title:
        variations.append(no_track_prefix)

    # Remove common artist prefixes if we can detect them
    # Pattern: "Artist - Track Name" or "Artist – Track Name"
    # This is tricky without knowing the artist, but we can try common patterns
    dash_split = re.split(r'\s*[-–—]\s*', title, 1)
    if len(dash_split) == 2:
        # Could be "Artist - Track" or "Track - Artist"
        # We'll add both possibilities
        variations.append(dash_split[0])  # First part
        variations.append(dash_split[1])  # Second part

    # Split on common separators and try each part
    # For titles like "Artist1 & Artist2 - Track Name"
    parts = re.split(r'\s*[&+]\s*|\s+and\s+|\s+,+\s*', title, flags=re.IGNORECASE)
    for part in parts:
        part = part.strip()
        if part and len(part) > 1:  # Avoid single characters
            variations.append(part)

    # Also try normalizing each variation
    normalized_variations = []
    for var in variations:
        norm_var = normalize_key(var)
        if norm_var:  # Only add if normalization doesn't result in empty string
            normalized_variations.append(norm_var)
        # Also add the original variation for cases where normalization loses too much
        normalized_variations.append(var)

    # Remove duplicates while preserving order
    seen = set()
    unique_variations = []
    for var in normalized_variations:
        if var not in seen:
            seen.add(var)
            unique_variations.append(var)

    return unique_variations


def _is_soundcloud_like_title(title):
    """Heuristic to detect if a title looks like it comes from SoundCloud
    (contains common separators used in SoundCloud metadata)."""
    if not title:
        return False
    return (' & ' in title or ' and ' in title.lower() or
            ',' in title)