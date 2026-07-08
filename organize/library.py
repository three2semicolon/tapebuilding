"""
library root and existing-file introspection.
"""

import os
import re
import glob


def resolve_library_root():
    """canonical library root: archive_path env var, else ~/music/tapebuilding."""
    return os.getenv('archive_path', os.path.expanduser('~/music/tapebuilding'))


def _normalize(s):
    """normalize a string for fuzzy matching — lowercase, strip punctuation/spaces."""
    s = s.lower()
    s = re.sub(r'[^\w\s]', '', s)   # strip punctuation
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def build_library_index(library_root):
    """scan library_root for audio files and return a set of normalized
    'artist - title' keys for fast existence lookup.

    Keys are normalized (lowercase, no punctuation) so they survive minor
    spotDL sanitization differences.
    """
    index = set()
    extensions = ('*.mp3', '*.flac', '*.m4a', '*.opus', '*.ogg', '*.wav', '*.aac')
    for ext in extensions:
        for filepath in glob.glob(os.path.join(library_root, ext)):
            stem = os.path.splitext(os.path.basename(filepath))[0]
            index.add(_normalize(stem))
    return index


def scan_existing(library_root, candidate_names):
    """count how many candidate filenames already exist under library_root.

    Falls back to direct os.path.exists check (original behavior) — use
    scan_existing_fuzzy for normalized matching against a pre-built index.

    Returns (existing, new).
    """
    existing = 0
    new = 0
    for name in candidate_names:
        if name and os.path.exists(os.path.join(library_root, name)):
            existing += 1
        else:
            new += 1
    return existing, new


def scan_existing_fuzzy(candidate_names, library_index):
    """check candidates against a pre-built normalized library index.

    candidate_names: list of predicted filenames (with or without extension)
    library_index: set of normalized stems from build_library_index()

    Returns (existing, new).
    """
    existing = 0
    new = 0
    for name in candidate_names:
        stem = os.path.splitext(name)[0]  # strip extension if present
        if _normalize(stem) in library_index:
            existing += 1
        else:
            new += 1
    return existing, new
