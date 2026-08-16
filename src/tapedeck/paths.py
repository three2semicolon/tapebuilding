
"""tapedeck/paths - resolve the three roots the tapedeck touches.

everything here just wraps the project's existing resolvers so the same
.env keys (ARCHIVE_PATH / TAPEDECK_PATH / PLAYLISTS_PATH) and the same --flag
overrides work everywhere. nothing is invented - each call delegates to
organize.library (crate + tapedeck) or playlists.indexer (playlists + exports).
"""

import os

from organize.library import resolve_library_root, resolve_tapedeck_root
from playlists.indexer import resolve_playlists_path, resolve_exports_dir


def crate_root(cli=None):
    """the source library - ARCHIVE_PATH / --archive-path."""
    return cli or resolve_library_root()


def tapedeck_root(cli=None):
    """the rotation destination - TAPEDECK_PATH / --tapedeck-path."""
    return resolve_tapedeck_root(cli)


def playlists_root(cli=None):
    """where the source .m3u8s live - PLAYLISTS_PATH / --playlists-path."""
    if not cli and not os.getenv('PLAYLISTS_PATH') and not os.getenv('playlists_path'):
        # resolve_playlists_path raises a ValueError with this hint; surface a
        # clearer one for the tapedeck context (playlists aren't strictly
        # required for album/song/soundtrack loads, only for `load playlist`).
        return None
    return resolve_playlists_path(cli)


def exports_dir(playlists_path=None, cli=None):
    """sidecar dir for the cached crate index (.playlist_index.jsonl)."""
    return resolve_exports_dir(playlists_path, cli)
