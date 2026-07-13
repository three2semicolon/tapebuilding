#!/usr/bin/env python3
"""indexer - build a local catalog of the music library for track matching.

walks the crate (`ARCHIVE_PATH`) recursively, reading audio tags with mediafile,
and caches the catalog to a jsonl sidecar in the exports dir. this is the matching
source for the playlist builder - it has to cover albums/, singles/ AND the
soundtracks/ tree (which beets.db does not index), so we tag-read the filesystem
rather than query beets. reuse `organize.cleanup`'s tag-reading idiom and
the same extension list.

usage (normally called from build.py):
  reindex = True            # rebuild the sidecar from disk
  index = get_index(library_root, exports_dir, reindex=True)
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

try:
    from mediafile import MediaFile
except ImportError:  # pragma: no cover
    sys.exit("mediafile not installed - run `uv sync` first (beets pulls it in).")

from organize.cleanup import EXTENSIONS  # ('.mp3','.flac','.m4a','.opus','.ogg','.wav','.aac')
from organize.library import resolve_library_root

INDEX_NAME = '.playlist_index.jsonl'

# top-level subdirs we never scan: the playlists tree holds .m3u8/.csv, not audio,
# and re-indexing would otherwise stat everything in exports/.
_SKIP_TOPLEVEL = {'playlists', '$RECYCLE.BIN', 'System Volume Information'}


def resolve_playlists_path(cli=None):
    """playlists destination, from --playlists-path or the dual-case env, no fallback."""
    path = cli or os.getenv('PLAYLISTS_PATH') or os.getenv('playlists_path')
    if not path:
        raise ValueError("PLAYLISTS_PATH not set - put it in .env (e.g. Y:/music/crate/playlists)")
    return path


def resolve_archive_path(cli=None):
    """crate root, from --archive-path or ARCHIVE_PATH env (via organize.library)."""
    return cli or resolve_library_root()


def resolve_exports_dir(playlists_path=None, cli=None):
    """where the existing spotify csvs live and where our sidecar logs go."""
    if cli:
        return cli
    base = playlists_path or resolve_playlists_path()
    exports = os.path.join(base, 'exports')
    os.makedirs(exports, exist_ok=True)
    return exports


def index_path(exports_dir):
    return os.path.join(exports_dir, INDEX_NAME)


def _read_entry(path):
    """return {path,artist,albumartist,album,title,track,length} or None on read error.
    extends organize.cleanup.read_tags with album + length (seconds) for matching."""
    try:
        m = MediaFile(path)
    except Exception:
        return None
    return {
        'path': path,
        'artist': (m.artist or '').strip(),
        'albumartist': (m.albumartist or '').strip(),
        'album': (m.album or '').strip(),
        'title': (m.title or '').strip(),
        'track': m.track or 0,
        'length': float(m.length) if m.length else 0.0,
    }


def build_index(library_root, skip_dirs=(_SKIP_TOPLEVEL,), verbose=False):
    """recursive mediafile tag walk over the crate -> list of entry dicts.

    skips the top-level playlists/ subtree and any dir whose name collides with
    the crate's playlist exports. prints progress every 1000 files; a 10k-track
    crate takes a couple of minutes cold (the sidecar makes subsequent runs instant)."""
    index = []
    scanned = 0
    root_basename = os.path.basename(os.path.normpath(library_root))
    for dirpath, dirnames, filenames in os.walk(library_root):
        # prune the playlists subtree (only at the crate top level, so an album
        # legitimately named "playlists" nested deeper isn't skipped)
        if os.path.basename(os.path.normpath(dirpath)) == root_basename:
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in EXTENSIONS:
                continue
            entry = _read_entry(os.path.join(dirpath, fn))
            if entry:
                index.append(entry)
            scanned += 1
            if verbose and scanned % 1000 == 0:
                print(f"  scanned {scanned} audio files...")
    return index


def save_index(index, path):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for e in index:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def load_index(path):
    """read the jsonl sidecar -> list, or None if missing/corrupt."""
    if not os.path.exists(path):
        return None
    index = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    index.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return None
    return index


def get_index(library_root, exports_dir, reindex=False, verbose=False):
    """return the local catalog, building the sidecar when missing or on --reindex."""
    sidecar = index_path(exports_dir)
    if not reindex and os.path.exists(sidecar):
        cached = load_index(sidecar)
        if cached is not None:
            print(f"using cached index ({len(cached)} tracks) at {sidecar}")
            return cached
    print(f"building index from {library_root} ...")
    index = build_index(library_root, verbose=verbose)
    save_index(index, sidecar)
    print(f"indexed {len(index)} tracks -> {sidecar}")
    return index
