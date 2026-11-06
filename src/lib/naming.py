"""lib.naming - shared filename/folder naming helpers.

Centralises naming logic duplicated between organize.preimport.plan and
organize.cleanup.grouping: zero-padded track labels, album folder names,
and singleton filenames.
"""

from lib.tags import sanitize
from lib.text import render_credit


def _track_label(idx, f):
    """Zero-padded two-digit track label: the file's tag track number, else
    the 1-based position in the group."""
    n = f['track'] or (idx + 1)
    return f"{int(n) if n else idx + 1:02d}"


def album_folder_name(albumartist, album):
    """Build an album folder name: sanitize("{render_credit(aa)} - {album}")
    or 'Unknown Album' if empty."""
    name = sanitize(f"{render_credit(albumartist)} - {album}") or 'Unknown Album'
    return name


def singleton_filename(artist, title, ext):
    """Build a singleton filename: "{sanitize(artist)} - {sanitize(title)}{ext}"."""
    return f"{sanitize(artist)} - {sanitize(title)}{ext or ''}"
