"""
library root and existing-file introspection.

"""

import os


def resolve_library_root():
    """canonical library root: archive_path env var, else ~/music/tapebuilding."""
    return os.getenv('archive_path', os.path.expanduser('~/music/tapebuilding'))


def scan_existing(library_root, candidate_names):
    """count how many candidate filenames already exist under library_root.

    Returns (existing, new). Candidate names are filenames only (no directory);
    they're joined with library_root before checking.
    """
    existing = 0
    new = 0
    for name in candidate_names:
        if name and os.path.exists(os.path.join(library_root, name)):
            existing += 1
        else:
            new += 1
    return existing, new
