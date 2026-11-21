"""app.services.library_index - in-memory crate index for the web app.

loads the shared crate index (lib.catalog.indexer.refresh_index) into memory
and serves paging/search/sort/filter from it. 10-50k rows filter in
milliseconds, so no SQLite.

the app stops using lib.tags.scan_audio for its library view; the shared
index covers albums/, singles/ AND soundtracks/ (which scan_audio's default
subdirs=('albums','singles') misses).
"""

from threading import RLock

from lib.catalog.indexer import refresh_index as _refresh_index
from lib.paths import archive_path, exports_dir, path_key


class LibraryIndex:
    """in-memory index of crate tracks with search, sort, and paging.

    rows are keyed by path_key() so membership lookups and tag-edit patches
    match regardless of separator/case differences between callers.
    """

    def __init__(self):
        self._rows = []          # list of entry dicts (with '_path_key' added)
        self._by_path = {}       # path_key -> entry dict
        self._state = "idle"     # idle | scanning | ready | error
        self._error = None
        self._lock = RLock()
        self._scanned = 0
        self._read = 0

    # -- lifecycle -------------------------------------------------------

    def status(self):
        """return {state, scanned, read, total, error} for /api/library/status."""
        with self._lock:
            return {
                "state": self._state,
                "scanned": self._scanned,
                "read": self._read,
                "total": len(self._rows),
                "error": self._error,
            }

    def load(self, library_root=None, exports_dir_value=None, force=False,
             workers=4, on_progress=None):
        """load (or incrementally refresh) the index into memory.

        every call goes through refresh_index(), which is cheap on a warm
        cache (stat-only comparison) and only reads changed/new files.
        """
        library_root = library_root or archive_path()
        exports_dir_value = exports_dir_value or exports_dir()

        def _do_load():
            with self._lock:
                self._state = "scanning"
                self._error = None

            index, stats = _refresh_index(
                library_root, exports_dir_value, workers=workers,
                on_progress=on_progress,
            )

            rows = []
            by_path = {}
            for e in index:
                e = dict(e)  # don't mutate the cached dict
                pk = path_key(e.get("path", ""))
                e["_path_key"] = pk
                rows.append(e)
                by_path[pk] = e

            with self._lock:
                self._rows = rows
                self._by_path = by_path
                self._state = "ready"
                self._scanned = stats.get("scanned", len(rows))
                self._read = stats.get("read", 0)
                self._error = None

        _do_load()

    # -- queries ---------------------------------------------------------

    def _snapshot(self):
        with self._lock:
            return list(self._rows), dict(self._by_path), self._state, self._error

    def rows(self, q="", artist="", album="", playlist=None, min_playlists=1,
             sort="artist", dir="asc", offset=0, limit=50, membership=None):
        """filter/sort/page the in-memory rows.

        playlist="none" -> rows not in any playlist
        playlist=<name> -> rows in that playlist
        min_playlists=N -> rows in at least N playlists
        membership: path_key -> [playlist names] (from the membership index)
        """
        rows, _, _, _ = self._snapshot()

        ql = q.lower()
        filtered = []
        for r in rows:
            haystack = " ".join([
                r.get("artist", "") or "",
                r.get("album", "") or "",
                r.get("title", "") or "",
            ]).lower()
            if ql and ql not in haystack:
                continue
            if artist and artist.lower() not in (r.get("artist", "") or "").lower():
                continue
            if album and album.lower() not in (r.get("album", "") or "").lower():
                continue
            if playlist is not None or min_playlists > 1:
                pls = membership.get(r["_path_key"], []) if membership else []
                if playlist == "none":
                    if pls:
                        continue
                elif playlist is not None and playlist not in pls:
                    continue
                if len(pls) < min_playlists:
                    continue
            filtered.append(r)

        total = len(filtered)

        reverse = dir == "desc"
        key_map = {
            "artist": lambda r: (r.get("artist", "") or "").lower(),
            "album": lambda r: (r.get("album", "") or "").lower(),
            "title": lambda r: (r.get("title", "") or "").lower(),
            "path": lambda r: r.get("path", ""),
        }
        keyfn = key_map.get(sort, key_map["artist"])
        filtered.sort(key=keyfn, reverse=reverse)

        page = filtered[offset:offset + limit]
        result = [{k: v for k, v in r.items() if not k.startswith("_")} for r in page]
        return {"total": total, "rows": result}

    def by_path(self, path):
        """return the entry dict for a crate path, or None."""
        _, by_path, _, _ = self._snapshot()
        return by_path.get(path_key(path))
