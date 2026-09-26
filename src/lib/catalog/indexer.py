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

the cached sidecar auto-invalidates: get_index() does a cheap stat-only walk
(mtimes only, no tag reads - see _newest_mtime()) before trusting the cache,
and rebuilds if anything under the crate is newer than the sidecar itself.
this was previously all-or-nothing on the caller passing --reindex, which
meant tracks added to the crate after the last index build were silently
invisible to every matcher tier until someone remembered to force a rebuild
by hand (found via a real unmatched.csv miss - see BUGFIX_PLAN.md's Bug 1).
--reindex still works as an explicit override.
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


def _newest_mtime(library_root, skip_dirs=_SKIP_TOPLEVEL, exclude_dir=None):
    """cheap stat-only walk over the same tree build_index() covers -> the
    newest mtime seen (directories and files both), or None if
    library_root doesn't exist. no tag reads - just os.stat(), so this is
    orders of magnitude cheaper than build_index()'s per-file read_tags()
    pass and safe to run before every get_index() call, cached or not.

    directories are stat'd too (not just files): removing a file leaves no
    mtime of its own to compare, but it does bump its parent directory's
    mtime, so a deletion still invalidates the cache instead of leaving a
    dangling entry that points at a file that's no longer there. exclude_dir
    is used by _is_stale() to keep the cache/export directory from invalidating
    the cache itself, which can otherwise happen from directory mtime updates
    on Windows."""
    if not os.path.isdir(library_root):
        return None
    newest = None
    root_basename = os.path.basename(os.path.normpath(library_root))
    exclude_dir = (
        os.path.normcase(os.path.abspath(exclude_dir))
        if exclude_dir
        else None
    )
    for dirpath, dirnames, filenames in os.walk(library_root):
        if exclude_dir:
            dirnames[:] = [
                d for d in dirnames
                if os.path.normcase(os.path.abspath(os.path.join(dirpath, d)))
                != exclude_dir
            ]
        if os.path.basename(os.path.normpath(dirpath)) == root_basename:
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        try:
            m = os.stat(dirpath).st_mtime
            newest = m if newest is None else max(newest, m)
        except OSError:
            pass
        for fn in filenames:
            try:
                m = os.stat(os.path.join(dirpath, fn)).st_mtime
            except OSError:
                continue
            newest = m if newest is None else max(newest, m)
    return newest


def _is_stale(sidecar, library_root):
    """True if the crate has changed since sidecar was last written, per
    _newest_mtime()'s cheap stat pass. Fails safe in both directions: a
    sidecar that vanishes mid-check counts as stale (forces a rebuild
    rather than serving a cache that's no longer even readable), while a
    library_root that can't be stat'd at all (permissions, a removable
    drive that dropped) counts as NOT stale, so a transient filesystem
    hiccup doesn't force an unwanted multi-minute reindex - it just serves
    the existing cache for that run."""
    try:
        sidecar_mtime = os.path.getmtime(sidecar)
    except OSError:
        return True
    newest = _newest_mtime(
        library_root,
        exclude_dir=os.path.dirname(os.path.abspath(sidecar)),
    )
    if newest is None:
        return False
    return newest > sidecar_mtime


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
    """return the cached catalog, building the sidecar when missing, on
    reindex, or when a cheap stat pass (_is_stale(), no tag reads) shows
    the crate has changed since the sidecar was last written.
    library_root/exports_dir_value default to the resolved crate and
    exports roots via lib.paths."""
    library_root = library_root or archive_path()
    exports_dir_value = exports_dir_value or exports_dir()
    sidecar = index_path(exports_dir_value)

    if not reindex and os.path.exists(sidecar):
        if _is_stale(sidecar, library_root):
            print(f"cached index at {sidecar} is older than the crate - rebuilding...")
        else:
            cached = load_index(sidecar)
            if cached is not None:
                print(f"using cached index ({len(cached)} tracks) at {sidecar}")
                return cached

    print(f"building index from {library_root} ...")
    index = build_index(library_root, verbose=verbose)
    save_index(index, sidecar)
    print(f"indexed {len(index)} tracks -> {sidecar}")
    return index
