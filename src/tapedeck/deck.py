
"""tapedeck/deck - load / list / unload the rotation.

the tapedeck is a small subset of the crate (ARCHIVE_PATH) mirrored 1:1 by
crate-relative path into TAPEDECK_PATH for syncthing to devices. `load` stages
albums / songs / soundtracks / playlists (resolved by crate path or by name via the
existing catalog + matcher); `list` summarises what's staged; `unload` removes them.
every mutating command is a dry run unless apply=True, matching the rest of the repo.

cli.py owns argument parsing / exit codes; load_tapedeck() / unload_tapedeck() /
list_tapedeck() below are the plain, import-safe entry points - no argparse/
sys.exit in here, so core/ can call these directly later without shelling out.

lib/ refactor: catalog index/matcher come from lib.catalog.indexer /
lib.catalog.matcher instead of the (now-deleted) playlists.indexer /
playlists.matcher. root resolution comes from lib.paths directly - the old
tapedeck/paths.py wrapper is gone entirely; see playlists_root() below for the
one bit of real behavior it carried (PLAYLISTS_PATH being optional here, unlike
lib.paths.playlists_path()'s hard requirement for playlists.build), now inlined
where it's actually used instead of living in its own file.

usage (via tapedeck's cli):
  uv run tapedeck load album "Captain Murphy - Duality Deluxe"       # preview
  uv run tapedeck load album "albums/Captain Murphy - Duality Deluxe" --apply
  uv run tapedeck load song "Halo" --apply --link
  uv run tapedeck load soundtrack "sonic unleashed" --apply
  uv run tapedeck load playlist "__mom" --apply
  uv run tapedeck list
  uv run tapedeck unload playlist "__mom" --apply
"""

import os

from lib.paths import (
    archive_path as crate_root,
    tapedeck_path as tapedeck_root,
    playlists_path as _resolve_playlists_path,
    exports_dir as resolve_exports_dir,
)
from lib.catalog.indexer import get_index
from lib.catalog.matcher import MatchIndex

from tapedeck.resolve import resolve_targets, need_index_for
from tapedeck.copy import stage, unstage


KINDS = ('album', 'song', 'soundtrack', 'playlist')


def playlists_root(cli=None):
    """where the source .m3u8s live - PLAYLISTS_PATH / --playlists-path, or
    None if unset. playlists aren't required for album/song/soundtrack loads,
    only for `load/unload playlist` and the exports-dir fallback in
    _maybe_index() - so unlike lib.paths.playlists_path() (required=True,
    since playlists.build genuinely can't run without it), this degrades to
    None instead of raising."""
    try:
        return _resolve_playlists_path(cli)
    except ValueError:
        return None


def _fmt_size(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def _maybe_index(kind, specs, crate, playlists_path=None, exports_dir=None,
                 reindex=False, verbose=False):
    """fetch the cached crate index + matcher only when the invocation needs
    name resolution (song-by-name, album-by-tag); path-only loads skip it."""
    if not need_index_for(kind, specs, crate):
        return None, None
    exp = resolve_exports_dir(playlists_path or os.path.join(crate, 'playlists'), exports_dir)
    index = get_index(crate, exp, reindex=reindex, verbose=verbose)
    return index, MatchIndex(index)


def load_tapedeck(kind, specs, apply=False, link=False, overwrite=False,
                  reindex=False, verbose=False, archive_path=None,
                  tapedeck_path=None, playlists_path=None, exports_dir=None):
    """stage the resolved kind/specs into the tapedeck. plain, import-safe
    entry point - cli.py resolves click options into these kwargs and turns
    exceptions into exit codes; nothing in here calls sys.exit()."""
    crate = crate_root(archive_path)
    deck = tapedeck_root(tapedeck_path)
    os.makedirs(deck, exist_ok=True)
    plist = playlists_root(playlists_path)
    index, mindex = _maybe_index(kind, specs, crate, playlists_path=plist,
                                 exports_dir=exports_dir, reindex=reindex, verbose=verbose)

    res = resolve_targets(kind, specs, crate, playlists_path=plist,
                          index=index, mindex=mindex, verbose=verbose)

    n_folders, n_files, n_m3u8 = map(len, (res['folders'], res['files'], res['m3u8']))
    print(f"\n{kind} load -> {n_folders} folder(s), {n_files} file(s), {n_m3u8} m3u8")
    for w in res['warnings']:
        print(f"  ! {w}")
    if res['warnings'] and not (n_folders or n_files or n_m3u8):
        return None  # nothing staged

    if not apply:
        print("\ndry run (no files written). stage plan:")
    else:
        print(f"\napplying -> {deck}")

    summary = stage(res, crate, deck, mode='link' if link else 'copy',
                    overwrite=overwrite, dry_run=not apply, verbose=verbose)
    if apply:
        _print_stage_summary(summary)
    return summary


def _print_stage_summary(s):
    parts = []
    if s['copied']:
        parts.append(f"{s['copied']} copied")
    if s['linked']:
        parts.append(f"{s['linked']} linked")
    if s['overwritten']:
        parts.append(f"{s['overwritten']} overwritten")
    if s['skipped']:
        parts.append(f"{s['skipped']} already present (skipped)")
    if s['errors']:
        parts.append(f"{s['errors']} errors")
    print(f"done: {', '.join(parts) or 'nothing to do'}.")


def unload_tapedeck(kind, specs, apply=False, verbose=False, archive_path=None,
                    tapedeck_path=None, playlists_path=None):
    """remove the resolved kind/specs from the tapedeck. plain, import-safe
    entry point - see load_tapedeck()."""
    crate = crate_root(archive_path)
    deck = tapedeck_root(tapedeck_path)
    plist = playlists_root(playlists_path)
    index, mindex = _maybe_index(kind, specs, crate, playlists_path=plist, verbose=verbose)

    res = resolve_targets(kind, specs, crate, playlists_path=plist,
                          index=index, mindex=mindex, verbose=verbose)

    n_folders, n_files, n_m3u8 = map(len, (res['folders'], res['files'], res['m3u8']))
    print(f"\n{kind} unload -> {n_folders} folder(s), {n_files} file(s), {n_m3u8} m3u8 to resolve")
    for w in res['warnings']:
        print(f"  ! {w}")
    if not (n_folders or n_files or n_m3u8):
        return None

    if not apply:
        print("\ndry run (no files removed). unload plan:")
    else:
        print(f"\napplying -> {deck}")

    summary = unstage(res, crate, deck, kind, dry_run=not apply, verbose=verbose)
    if apply:
        parts = []
        if summary['removed']:
            parts.append(f"{summary['removed']} files removed")
        if summary['m3u8_removed']:
            parts.append(f"{summary['m3u8_removed']} m3u8 removed")
        if summary['protected']:
            parts.append(f"{summary['protected']} kept (referenced by another playlist)")
        if summary['missing']:
            parts.append(f"{summary['missing']} already absent")
        if summary['errors']:
            parts.append(f"{summary['errors']} errors")
        print(f"done: {', '.join(parts) or 'nothing removed'}.")
    return summary


def list_tapedeck(kind=None, tapedeck_path=None, verbose=False):
    """summarise what's staged on the tapedeck. plain, import-safe entry
    point - see load_tapedeck()."""
    deck = tapedeck_root(tapedeck_path)
    if not os.path.isdir(deck):
        print(f"tapedeck not found: {deck}")
        return None
    print(f"tapedeck: {deck}")

    stats = {}
    total_files = 0
    total_bytes = 0
    for sub in ('albums', 'singles', 'soundtracks', 'playlists'):
        root = os.path.join(deck, sub)
        if not os.path.isdir(root):
            continue
        folder_files = {}        # rel-dir-or-None -> [files]; None = directly under root
        for dp, _, fns in os.walk(root):
            for fn in fns:
                fp = os.path.join(dp, fn)
                key = os.path.relpath(dp, root) if dp != root else None
                folder_files.setdefault(key, []).append(fp)
        files = [f for grp in folder_files.values() for f in grp]
        size = sum(os.path.getsize(f) for f in files)
        stats[sub] = {'files': len(files),
                      'folders': sum(1 for k in folder_files if k is not None),
                      'size': size, 'root': root, 'groups': folder_files}
        total_files += len(files)
        total_bytes += size

    if not stats:
        print("  (empty - nothing staged yet)")
        return stats

    print(f"  {total_files} files, {_fmt_size(total_bytes)}\n")

    kind_to_sub = {'album': 'albums', 'song': 'singles', 'soundtrack': 'soundtracks',
                   'playlist': 'playlists'}
    subs = [kind_to_sub[kind]] if kind else \
           [s for s in ('albums', 'singles', 'soundtracks', 'playlists') if s in stats]

    labels = {'albums': 'Albums', 'singles': 'Singles',
              'soundtracks': 'Soundtracks', 'playlists': 'Playlists'}
    for sub in subs:
        s = stats[sub]
        head = [f"{s['files']} files"]
        if s['folders']:
            head.insert(0, f"{s['folders']} folder(s)")
        print(f"{labels[sub]:<12} {', '.join(head)}, {_fmt_size(s['size'])}")
        if not verbose:
            continue
        if sub in ('singles', 'playlists'):              # flat: one .m3u8 / single per entry
            for f in sorted(s['groups'].get(None, [])):
                print(f"    {os.path.basename(f)}  ({_fmt_size(os.path.getsize(f))})")
        else:                                             # nested: per-folder summary
            for key in sorted(k for k in s['groups'] if k is not None):
                grp = s['groups'][key]
                sz = _fmt_size(sum(os.path.getsize(x) for x in grp))
                print(f"    {key}  ({len(grp)} files, {sz})")
    return stats
