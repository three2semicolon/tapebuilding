"""app.services.membership - path -> playlist membership index.

maps an absolute track path to the list of playlist names that contain it.
keys are :func:`lib.paths.path_key` values so ``Y:/Music/Crate/a.mp3`` and
``y:/music/crate/A.MP3`` match. rebuilt incrementally: the index is cached and
only reconstructed when a playlist file's mtime changes, or when
:invalidate: is called (e.g. after the app writes a playlist).

"exists" means present in the index - no per-path :func:`os.path.isfile`
probe at request time.
"""

import os
from threading import RLock

from lib.m3u import read_m3u8
from lib.paths import path_key, playlists_path


class MembershipIndex:
    """path_key -> [playlist names, ...] across every .m3u8, mtime-cached."""

    def __init__(self):
        self._index = {}        # path_key -> [playlist_name, ...]
        self._mtime = 0.0       # newest playlist mtime seen at last build
        self._pl_dir = None     # playlists dir the cache was built for
        self._lock = RLock()

    def build(self, force=False):
        """rebuild if any playlist mtime changed (or force), else return cache."""
        pl_dir = playlists_path()
        newest = 0.0
        if os.path.isdir(pl_dir):
            for name in os.listdir(pl_dir):
                if not name.lower().endswith((".m3u", ".m3u8")):
                    continue
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(pl_dir, name)))
                except OSError:
                    pass

        with self._lock:
            if not force and self._index and self._pl_dir == pl_dir and newest == self._mtime:
                return self._index

            index = {}
            if os.path.isdir(pl_dir):
                for name in sorted(os.listdir(pl_dir)):
                    if not name.lower().endswith((".m3u", ".m3u8")):
                        continue
                    for p in read_m3u8(os.path.join(pl_dir, name))["existing"]:
                        index.setdefault(path_key(p), []).append(name)
            self._index = index
            self._mtime = newest
            self._pl_dir = pl_dir
            return self._index

    def invalidate(self):
        """drop the cache so the next build() reconstructs from disk."""
        with self._lock:
            self._index = {}
            self._mtime = 0.0
            self._pl_dir = None


# module-level singleton used by the app's routes
_membership = MembershipIndex()


def build_index():
    """Return {path_key: [playlist_name, ...]} across every .m3u8.

    kept as a module-level function for existing callers/tests; prefers the
    cached singleton so repeated calls are cheap.
    """
    return _membership.build()


def invalidate_index():
    """tell the membership index to rebuild on next use (call after the app
    writes or deletes a playlist)."""
    _membership.invalidate()
