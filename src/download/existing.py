"""download.existing - fast, filename-only existence check against the crate,
used before a download run to skip tracks already on disk.

was organize.library.build_library_index / scan_existing / scan_existing_fuzzy
(and organize.library._normalize, now lib.text.normalize_key). rehomed here
rather than into lib/ because this is genuinely download-specific: it's a
different, cheaper check than lib.catalog's tag-based index.

why not just use lib.catalog.get_index()? that builds/caches a full tag read
of every file (MediaFile per track) - correct for playlist matching, overkill
for "does a file predicted-named '<artist> - <title>.<ext>' already exist".
spotdl/yt-dlp write predictable filenames, so a plain recursive filename-stem
glob is enough, and it's cheap enough to redo every run instead of needing a
cache sidecar.

used by spotify_download.py's --pre-skip-existing / --validate-only path;
also imported directly by ytdl.py for the same output-dir resolution, so
both commands resolve output the same way from this one place.
"""

import os

from lib.paths import archive_path
from lib.tags import EXTENSIONS
from lib.text import normalize_key


def resolve_output_dir(output_dir=None):
    """resolve the download output directory: explicit -o/--output override,
    else ARCHIVE_PATH (lib.paths.archive_path()'s own ~/music/tapebuilding
    convenience default). creates the directory if it doesn't exist yet -
    spotdl/yt-dlp don't reliably create intermediate directories themselves
    on Windows.

    shared by spotify_download.py and ytdl.py so both resolve output the
    same way (see this module's docstring).
    """
    resolved = archive_path(cli=output_dir)
    os.makedirs(resolved, exist_ok=True)
    return resolved


def build_library_index(library_root):
    """recursive filename-stem scan of library_root -> a set of
    normalize_key()'d stems (extension stripped). no tag reads - just a
    directory walk, so this is fast even against a large crate."""
    index = set()
    if not library_root or not os.path.isdir(library_root):
        return index
    for dirpath, dirnames, filenames in os.walk(library_root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in filenames:
            if not fn.lower().endswith(EXTENSIONS):
                continue
            stem = os.path.splitext(fn)[0]
            index.add(normalize_key(stem))
    return index


def scan_existing_fuzzy(candidate_filenames, library_index):
    """check predicted filenames against a build_library_index() result,
    normalizing both sides before comparing (handles case/punctuation drift
    between spotdl's sanitization and whatever's actually on disk).

    returns (existing_count, new_count).
    """
    existing = 0
    new = 0
    for filename in candidate_filenames:
        stem = os.path.splitext(filename)[0]
        if normalize_key(stem) in library_index:
            existing += 1
        else:
            new += 1
    return existing, new
