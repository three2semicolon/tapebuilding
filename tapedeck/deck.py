
"""tapedeck/deck - load / list / unload the rotation.

the tapedeck is a small subset of the crate (`ARCHIVE_PATH`) mirrored 1:1 by
crate-relative path into `TAPEDECK_PATH` for syncthing to devices. `load` stages
albums / songs / soundtracks / playlists (resolved by crate path or by name via the
existing index + matcher); `list` summarises what's staged; `unload` removes them.
every mutating command is a dry run unless `--apply`, matching the rest of the repo.

usage:
  uv run tapedeck load album "Captain Murphy - Duality Deluxe"       # preview
  uv run tapedeck load album "albums/Captain Murphy - Duality Deluxe" --apply
  uv run tapedeck load song "Halo" --apply --link
  uv run tapedeck load soundtrack "sonic unleashed" --apply
  uv run tapedeck load playlist "__mom" --apply
  uv run tapedeck list
  uv run tapedeck unload playlist "__mom" --apply
"""

import argparse
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from playlists.indexer import get_index
from playlists.matcher import MatchIndex

from .paths import crate_root, tapedeck_root, playlists_root, exports_dir
from .resolve import resolve_targets, need_index_for
from .copy import stage, unstage

try:
    sys.stdout.reconfigure(encoding='utf-8')  # non-ascii artist names on windows
except Exception:
    pass


KINDS = ('album', 'song', 'soundtrack', 'playlist')


def _fmt_size(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def _maybe_index(args, kind, specs, crate):
    """fetch the cached crate index + matcher only when the invocation needs
    name resolution (song-by-name, album-by-tag); path-only loads skip it."""
    if not need_index_for(kind, specs, crate):
        return None, None
    exp = exports_dir(playlists_root() or os.path.join(crate, 'playlists'), args.exports_dir)
    index = get_index(crate, exp, reindex=args.reindex, verbose=args.verbose)
    return index, MatchIndex(index)


def _load(args):
    crate = crate_root(args.archive_path)
    tapedeck = tapedeck_root(args.tapedeck_path)
    os.makedirs(tapedeck, exist_ok=True)
    plist = playlists_root(args.playlists_path)
    index, mindex = _maybe_index(args, args.kind, args.specs, crate)

    res = resolve_targets(args.kind, args.specs, crate, playlists_path=plist,
                          index=index, mindex=mindex, verbose=args.verbose)

    n_folders, n_files, n_m3u8 = map(len, (res['folders'], res['files'], res['m3u8']))
    print(f"\n{args.kind} load -> {n_folders} folder(s), {n_files} file(s), {n_m3u8} m3u8")
    for w in res['warnings']:
        print(f"  ! {w}")
    if res['warnings'] and not (n_folders or n_files or n_m3u8):
        return  # nothing staged

    if not args.apply:
        print("\ndry run (no files written). stage plan:")
    else:
        print(f"\napplying -> {tapedeck}")

    summary = stage(res, crate, tapedeck, mode='link' if args.link else 'copy',
                    overwrite=args.overwrite, dry_run=not args.apply, verbose=args.verbose)
    if args.apply:
        _print_stage_summary(summary, args.link)


def _print_stage_summary(s, link):
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


def _unload(args):
    crate = crate_root(args.archive_path)
    deck = tapedeck_root(args.tapedeck_path)
    plist = playlists_root(args.playlists_path)
    index, mindex = _maybe_index(args, args.kind, args.specs, crate)

    res = resolve_targets(args.kind, args.specs, crate, playlists_path=plist,
                          index=index, mindex=mindex, verbose=args.verbose)

    n_folders, n_files, n_m3u8 = map(len, (res['folders'], res['files'], res['m3u8']))
    print(f"\n{args.kind} unload -> {n_folders} folder(s), {n_files} file(s), {n_m3u8} m3u8 to resolve")
    for w in res['warnings']:
        print(f"  ! {w}")
    if not (n_folders or n_files or n_m3u8):
        return

    if not args.apply:
        print("\ndry run (no files removed). unload plan:")
    else:
        print(f"\napplying -> {deck}")

    summary = unstage(res, crate, deck, args.kind, dry_run=not args.apply, verbose=args.verbose)
    if args.apply:
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


def _list(args):
    deck = tapedeck_root(args.tapedeck_path)
    if not os.path.isdir(deck):
        print(f"tapedeck not found: {deck}")
        return
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
        return

    print(f"  {total_files} files, {_fmt_size(total_bytes)}\n")

    kind_to_sub = {'album': 'albums', 'song': 'singles', 'soundtrack': 'soundtracks',
                   'playlist': 'playlists'}
    subs = [kind_to_sub[args.kind]] if args.kind else \
           [s for s in ('albums', 'singles', 'soundtracks', 'playlists') if s in stats]

    labels = {'albums': 'Albums', 'singles': 'Singles',
              'soundtracks': 'Soundtracks', 'playlists': 'Playlists'}
    for sub in subs:
        s = stats[sub]
        head = [f"{s['files']} files"]
        if s['folders']:
            head.insert(0, f"{s['folders']} folder(s)")
        print(f"{labels[sub]:<12} {', '.join(head)}, {_fmt_size(s['size'])}")
        if not args.verbose:
            continue
        if sub in ('singles', 'playlists'):              # flat: one .m3u8 / single per entry
            for f in sorted(s['groups'].get(None, [])):
                print(f"    {os.path.basename(f)}  ({_fmt_size(os.path.getsize(f))})")
        else:                                             # nested: per-folder summary
            for key in sorted(k for k in s['groups'] if k is not None):
                grp = s['groups'][key]
                sz = _fmt_size(sum(os.path.getsize(x) for x in grp))
                print(f"    {key}  ({len(grp)} files, {sz})")


def _add_kind_spec(parser):
    parser.add_argument('kind', choices=KINDS,
                        help='what to resolve the spec against')
    parser.add_argument('specs', nargs='+', metavar='SPEC',
                        help='crate-relative path/folder/file OR a name resolved by index/folder match')


def main():
    p = argparse.ArgumentParser(prog='tapedeck',
                                 description='load / list / unload the rotation crate into the tapedeck.')
    sub = p.add_subparsers(dest='command', required=True)

    lp = sub.add_parser('load', help='stage albums/songs/soundtracks/playlists into the tapedeck')
    _add_kind_spec(lp)
    lp.add_argument('--apply', action='store_true', help='actually copy/link (default is a dry-run preview)')
    lp.add_argument('--link', action='store_true', help='hardlink instead of copy (same volume only)')
    lp.add_argument('--overwrite', action='store_true', help='replace an existing dst instead of skipping')
    lp.add_argument('--reindex', action='store_true', help='rebuild the cached crate index first (song/album-by-name)')
    lp.add_argument('--verbose', action='store_true', help='print every file action')
    lp.add_argument('--archive-path', help='ARCHIVE_PATH (crate root) override')
    lp.add_argument('--tapedeck-path', help='TAPEDECK_PATH override')
    lp.add_argument('--playlists-path', help='PLAYLISTS_PATH override')
    lp.add_argument('--exports-dir', help='exports dir override (cached index sidecar)')
    lp.set_defaults(func=_load)

    up = sub.add_parser('unload', help='remove albums/songs/soundtracks/playlists from the tapedeck')
    _add_kind_spec(up)
    up.add_argument('--apply', action='store_true', help='actually remove (default is a dry-run preview)')
    up.add_argument('--overwrite', action='store_true', help=argparse.SUPPRESS)  # accepted for parity, unused
    up.add_argument('--verbose', action='store_true', help='print every file action')
    up.add_argument('--archive-path', help='ARCHIVE_PATH (crate root) override')
    up.add_argument('--tapedeck-path', help='TAPEDECK_PATH override')
    up.add_argument('--playlists-path', help='PLAYLISTS_PATH override')
    up.add_argument('--exports-dir', help=argparse.SUPPRESS)
    up.set_defaults(func=_unload)

    lst = sub.add_parser('list', help='show what is staged on the tapedeck')
    lst.add_argument('--kind', choices=KINDS, help='limit to one subtree')
    lst.add_argument('--tapedeck-path', help='TAPEDECK_PATH override')
    lst.add_argument('--verbose', action='store_true', help='per-folder / per-file detail')
    lst.set_defaults(func=_list)

    args = p.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
