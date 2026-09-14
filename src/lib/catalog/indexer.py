"""lib.catalog.indexer - build a searchable catalog of the crate for track
matching.

walks the crate recursively, reading audio tags via lib.tags.read_tags, and
caches the catalog to a jsonl sidecar under PLAYLISTS_PATH/exports. this has
to cover albums/, singles/, AND the soundtracks/ tree - beets.db does not
index soundtracks/, so playlists and tapedeck both read the filesystem
directly here instead of querying beets.

promoted out of playlists/ during the lib/ refactor: tapedeck depended on
this just as much as playlists did, so it belongs to the shared catalog
layer rather than one package.
"""

import json
import os
from pathlib import Path

from lib.paths import archive_path, exports_dir
from lib.tags import EXTENSIONS, read_tags

INDEX_NAME = '.playlist_index.jsonl'

# top-level subdirs never scanned: the playlists tree holds .m3u8/.csv, not
# audio, and re-indexing would otherwise stat everything under exports/.
_SKIP_TOPLEVEL = {'playlists', '$RECYCLE.BIN', 'System Volume Information'}


def index_path(exports_dir_value):
    return os.path.join(exports_dir_value, INDEX_NAME)


def build_index(library_root, skip_dirs=_SKIP_TOPLEVEL, verbose=False):
    """recursive tag walk over the crate -> list of entry dicts (see
    lib.tags.read_tags for shape). prints progress every 1000 files; a 10k-
    track crate takes a couple of minutes cold (the sidecar makes
    subsequent runs instant)."""
    index = []
    scanned = 0
    root_basename = os.path.basename(os.path.normpath(library_root))
    for dirpath, dirnames, filenames in os.walk(library_root):
        # prune the playlists subtree only at the crate top level, so an
        # album legitimately named "playlists" nested deeper isn't skipped
        if os.path.basename(os.path.normpath(dirpath)) == root_basename:
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in EXTENSIONS:
                continue
            entry = read_tags(os.path.join(dirpath, fn))
            if entry:
                index.append(entry)
            scanned += 1
            if verbose and scanned % 1000 == 0:
                print(f"  scanned {scanned} audio files...")
    return index


def save_index(index, path):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
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


def get_index(library_root=None, exports_dir_value=None, reindex=False, verbose=False):
    """return the cached catalog, building the sidecar when missing or on
    reindex. library_root/exports_dir_value default to the resolved crate
    and exports roots via lib.paths."""
    library_root = library_root or archive_path()
    exports_dir_value = exports_dir_value or exports_dir()
    sidecar = index_path(exports_dir_value)
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
