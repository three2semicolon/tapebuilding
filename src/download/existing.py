"""download.existing - existence check against the crate, used before a
download run to skip tracks already on disk.

was organize.library.build_library_index / scan_existing / scan_existing_fuzzy
(and organize.library._normalize, now lib.text.normalize_key). rehomed here
rather than into lib/ because this is genuinely download-specific.

two matching strategies, checked in order:
  1. filename-stem match (fast, no tag reads) - catches exact filename matches
  2. tag-based match (reads tags via mediafile) - catches files whose filename
     differs from the prediction (track-number prefixes like "01 - ", parentheticals,
     remix tags, etc.) - same approach preimport's find_duplicates() uses.

spotdl/yt-dlp write predictable filenames, so strategy 1 covers most cases and
strategy 2 only runs when there are filename misses.

used by spotify_download.py's --pre-skip-existing / --validate-only path;
also imported directly by ytdl.py for the same output-dir resolution, so
both commands resolve output the same way from this one place.
"""

import os

from lib.paths import archive_path
from lib.tags import EXTENSIONS, read_tags
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
    """recursive scan of library_root -> dict with:
      - 'stems': set of normalize_key(filename stems) for all audio files
      - 'paths': list of (path, stem) tuples for tag-based fallback matching

    Strategy 1 (filename stems) is fast - just a directory walk, no tag reads.
    Strategy 2 (tags) reads tags via lib.tags.read_tags and is only used as a
    fallback for filenames that don't match by stem."""
    stems = set()
    paths = []
    if not library_root or not os.path.isdir(library_root):
        return {'stems': stems, 'paths': paths}
    for dirpath, dirnames, filenames in os.walk(library_root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in filenames:
            if not fn.lower().endswith(EXTENSIONS):
                continue
            path = os.path.join(dirpath, fn)
            stem = os.path.splitext(fn)[0]
            stems.add(normalize_key(stem))
            paths.append((path, stem))
    return {'stems': stems, 'paths': paths}


def build_tag_index(paths):
    """read tags for every file path and return a dict of
    normalize_key(artist)|normalize_key(title) -> set of paths.

    Same tag-based matching preimport uses (artist+title via find_duplicates),
    minus the duration tolerance - the pre-skip check just needs to know
    "does this track already exist somewhere in the crate". Reads tags via
    mediafile, so this is slower than the filename-stem scan and is only
    invoked as a fallback for filename misses."""
    index = {}
    for path, _stem in paths:
        tags = read_tags(path)
        if not tags:
            continue
        artist = (tags.get('artist') or '').strip()
        title = (tags.get('title') or '').strip()
        if not artist or not title:
            continue
        key = normalize_key(artist) + '|' + normalize_key(title)
        index.setdefault(key, set()).add(path)
    return index


def scan_existing_fuzzy(candidate_filenames, library_index):
    """check predicted filenames against a build_library_index() result,
    normalizing both sides before comparing (handles case/punctuation drift
    between spotdl's sanitization and whatever's actually on disk).

    library_index is the dict from build_library_index(); reads
    library_index['stems'].

    returns (existing_count, new_count).
    """
    stems = library_index['stems'] if isinstance(library_index, dict) else library_index
    existing = 0
    new = 0
    for filename in candidate_filenames:
        stem = os.path.splitext(filename)[0]
        if normalize_key(stem) in stems:
            existing += 1
        else:
            new += 1
    return existing, new
