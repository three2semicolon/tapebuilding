"""lib.catalog.indexer - build a searchable catalog of the crate for track
matching.

walks the crate recursively, reading audio tags via lib.tags.read_tags, and
caches the catalog to a jsonl sidecar under PLAYLISTS_PATH/exports. this has
to cover albums/, singles/, AND the soundtracks/ tree - beets.db does not
index soundtracks/, so playlists and tapedeck both read the filesystem
directly here instead of querying beets.

top-level duplicates/ and unorganized/ are never scanned (Bug 12): they are
staging directories, not crate content, so the walk prunes them along with
playlists/ and the system recycle dirs (see _SKIP_TOPLEVEL).

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lib.paths import archive_path, exports_dir
from lib.tags import EXTENSIONS, read_tags

INDEX_NAME = ".playlist_index.jsonl"

# top-level subdirs never scanned: the playlists tree holds .m3u8/.csv, not
# audio, and re-indexing would otherwise stat everything under exports/.
SKIP_TOPLEVEL = {"playlists", "$RECYCLE.BIN", "System Volume Information", "duplicates", "unorganized"}


def index_path(exports_dir_value):
    return os.path.join(exports_dir_value, INDEX_NAME)


def build_index(library_root, skip_dirs=SKIP_TOPLEVEL, verbose=False):
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


def refresh_index(library_root, exports_dir_value, workers=4, on_progress=None, on_batch=None):
    """incrementally refresh the crate index.

    walks the crate, compares ``(mtime_ns, size)`` per audio file against the
    cached sidecar, reads only new/changed files via :func:`read_tags`,
    drops vanished ones, and atomically writes the sidecar (periodically
    during a cold build so an interrupted run isn't lost).

    returns ``(index, stats)`` where ``stats`` is a dict with
    ``scanned``, ``read``, ``skipped``, ``removed``, ``total``.

    old sidecars that lack ``mtime_ns``/``size`` keys cause one full rebuild
    as migration; after that every call is incremental.
    """
    library_root = library_root or archive_path()
    exports_dir_value = exports_dir_value or exports_dir()
    sidecar = index_path(exports_dir_value)

    # load existing sidecar (if any) and index by normpath
    cached = load_index(sidecar) or []
    by_path = {}
    for e in cached:
        p = e.get("path")
        if p:
            by_path[os.path.normpath(p)] = e

    # walk crate and stat every audio file
    current = {}  # normpath -> (mtime_ns, size, abs_path)
    root_basename = os.path.basename(os.path.normpath(library_root))
    for dirpath, dirnames, filenames in os.walk(library_root):
        if os.path.basename(os.path.normpath(dirpath)) == root_basename:
            dirnames[:] = [d for d in dirnames if d not in SKIP_TOPLEVEL]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in EXTENSIONS:
                continue
            full = os.path.join(dirpath, fn)
            try:
                st = os.stat(full)
                np = os.path.normpath(full)
                current[np] = (st.st_mtime_ns, st.st_size, full)
            except OSError:
                continue

    # classify: new or changed files need tag reads; unchanged ones are kept
    to_read = []
    for np, (mtime_ns, size, full) in current.items():
        cached_entry = by_path.get(np)
        if cached_entry is None:
            to_read.append(full)  # new file
        elif cached_entry.get("mtime_ns") != mtime_ns or cached_entry.get("size") != size:
            to_read.append(full)  # changed file

    # read new/changed files (threaded over I/O-bound tag parsing)
    new_entries = {}
    if to_read:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(read_tags, path): path for path in to_read}
            done = 0
            for future in as_completed(futures):
                path = futures[future]
                entry = future.result()
                done += 1
                if entry:
                    try:
                        st = os.stat(path)
                        entry["mtime_ns"] = st.st_mtime_ns
                        entry["size"] = st.st_size
                    except OSError:
                        entry["mtime_ns"] = 0
                        entry["size"] = 0
                    new_entries[os.path.normpath(path)] = entry
                if on_progress:
                    on_progress(done, len(to_read))

    # build final index: unchanged cached entries + newly read entries
    index = []
    removed = 0
    for np, entry in by_path.items():
        if np not in current:
            removed += 1  # vanished from disk
            continue
        mtime_ns, size, _ = current[np]
        if entry.get("mtime_ns") == mtime_ns and entry.get("size") == size:
            index.append(entry)  # unchanged - keep cached entry as-is
        else:
            np_entry = new_entries.get(np)
            if np_entry:
                index.append(np_entry)  # newly read replacement

    # add any new entries not already in by_path (shouldn't happen, but safe)
    for np, entry in new_entries.items():
        if np not in by_path:
            index.append(entry)

    # deterministic sort: artist, album, track, title
    index.sort(
        key=lambda e: (
            (e.get("artist") or "").lower(),
            (e.get("album") or "").lower(),
            e.get("track") or 0,
            (e.get("title") or "").lower(),
        )
    )

    # atomic write
    save_index(index, sidecar)

    stats = {
        "scanned": len(current),
        "read": len(new_entries),
        "skipped": len(current) - len(new_entries) - removed,
        "removed": removed,
        "total": len(index),
    }
    return index, stats


def _newest_mtime(library_root, skip_dirs=SKIP_TOPLEVEL, exclude_dir=None):
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
    exclude_dir = os.path.normcase(os.path.abspath(exclude_dir)) if exclude_dir else None
    for dirpath, dirnames, filenames in os.walk(library_root):
        if exclude_dir:
            dirnames[:] = [d for d in dirnames if os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) != exclude_dir]
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
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in index:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def load_index(path):
    """read the jsonl sidecar -> list, or None if missing/corrupt."""
    if not os.path.exists(path):
        return None
    index = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    index.append(json.loads(line))
    except OSError, json.JSONDecodeError:
        return None
    return index


def get_index(library_root=None, exports_dir_value=None, reindex=False, verbose=False):
    """return the cached catalog, building the sidecar when missing, on
    reindex, or incrementally refreshing when a cheap stat pass
    (_is_stale(), no tag reads) shows the crate has changed.

    library_root/exports_dir_value default to the resolved crate and
    exports roots via lib.paths. on a cache hit (nothing changed) the
    existing sidecar is returned with zero tag reads."""
    library_root = library_root or archive_path()
    exports_dir_value = exports_dir_value or exports_dir()
    sidecar = index_path(exports_dir_value)

    if reindex or not os.path.exists(sidecar):
        print(f"building index from {library_root} ...")
        index, _stats = refresh_index(library_root, exports_dir_value)
        print(f"indexed {len(index)} tracks -> {sidecar}")
        return index

    if not _is_stale(sidecar, library_root):
        cached = load_index(sidecar)
        if cached is not None:
            print(f"using cached index ({len(cached)} tracks) at {sidecar}")
            return cached

    print(f"cached index at {sidecar} is older than the crate - refreshing...")
    index, stats = refresh_index(library_root, exports_dir_value)
    print(f"indexed {len(index)} tracks ({stats['read']} read, {stats['removed']} removed) -> {sidecar}")
    return index
