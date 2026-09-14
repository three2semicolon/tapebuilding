"""core.sync - the README-documented `playlists --apply --rescrape` flow,
promoted to an actual function.

was: `uv run playlists --apply --rescrape` (a documented one-liner, no
dedicated wrapper, since playlists.build already does all three steps -
rescrape spotify, match against the crate, write .m3u8s - itself). This
module exists purely so app/ (and anything else calling into core/ later)
has an in-process function to call, for symmetry with download_songs.py -
no logic was extracted or changed, this is a thin promotion.
"""

from playlists.build import build_playlists


def run_sync(names=None, covers=False, verbose=False, playlists_path=None,
            archive_path=None, exports_dir=None):
    """rescrape spotify + rebuild every (or named) playlist's .m3u8, in one
    call. plain, import-safe entry point - mirrors
    `playlists --apply --rescrape [--covers] [-p NAME ...]` exactly. no
    dry-run mode of its own: a sync's whole point is writing the refreshed
    .m3u8s. for a preview of what a sync would resolve without writing
    anything, call `playlists.build.build_playlists(apply=False, ...)`
    directly instead (optionally with rescrape=True if you also want a
    fresh export first)."""
    return build_playlists(
        apply=True,
        rescrape=True,
        names=names or [],
        covers=covers,
        verbose=verbose,
        playlists_path=playlists_path,
        archive_path=archive_path,
        exports_dir=exports_dir,
    )
