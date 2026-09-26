"""organize.cleanup.apply - run_cleanup(): the regular regroup-in-place
pass. calls grouping.py's group_files()/build_plan() to decide the
plan, then performs the moves + albumartist tag-writes and prints the
dry-run/applied report. cli.py's `organize cleanup` (no --resplit)
entry point.
"""

import os
import sys

from lib.tags import dominant_album, safe_move, scan_audio, write_tag

from .common import resolve_crate
from .grouping import build_plan, group_files


def prune_empty_dirs(crate):
    for sub in ('albums', 'singles'):
        root = os.path.join(crate, sub)
        if not os.path.isdir(root):
            continue
        for dp, dirs, fns in os.walk(root, topdown=False):
            if dp == root:
                continue
            try:
                if not dirs and not fns:
                    os.rmdir(dp)
            except OSError:
                pass


def rebuild_db(crate, config_path):
    """fresh beets.db matching the reorganized crate: delete the old db, then
    as-is reimport (no autotag, no MusicBrainz lookups) of albums/ and singles/."""
    import subprocess
    db = os.path.join(crate, 'beets.db')
    if os.path.exists(db):
        os.remove(db)
    base = [sys.executable, '-m', 'beets', '--config', config_path,
            '--directory', crate, '--library', db]
    print("\n=== rebuilding beets.db (as-is, no musicbrainz) ===")
    if os.path.isdir(os.path.join(crate, 'albums')):
        print("  importing albums/...")
        subprocess.run(base + ['import', '-A', '-q', os.path.join(crate, 'albums')], check=False)
    if os.path.isdir(os.path.join(crate, 'singles')):
        print("  importing singles/...")
        subprocess.run(base + ['import', '-A', '-q', '-s', os.path.join(crate, 'singles')], check=False)
    print("  done. library.csv will regenerate on the next export.")


def config_path():
    """config.yaml sits in organize/, one level up from this file - this
    module moved into the organize/cleanup/ subpackage during the
    cleanup.py split, so unlike the old single-file cleanup.py this
    needs dirname() twice, not once."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')


def run_cleanup(crate=None, apply=False, no_tag_write=False,
                rebuild_db_flag=False, verbose=False):
    """regroup <crate>/albums + <crate>/singles in place. plain, import-safe
    entry point - does its own printing (dry-run plan, then the applied
    summary), same convention as download's export/download functions.
    cli.py resolves args and calls this; no argparse/sys.exit in here."""
    sys.stdout.reconfigure(encoding='utf-8')  # non-ASCII artist names won't crash the console
    sys.stderr.reconfigure(encoding='utf-8')

    crate = resolve_crate(crate)

    print(f"crate : {crate}")
    print(f"mode  : {'apply (files move, tags written)' if apply else 'dry run (nothing moves)'}")
    print()

    files = scan_audio(crate)
    print(f"scanned {len(files)} audio files")
    groups = group_files(files)
    album_moves, singleton_moves, noop, tag_writes, va_groups, split_groups = build_plan(groups, crate)

    album_groups = sum(1 for k, m in groups.items() if k[0] == 'album' and len(m) > 1)
    singleton_count = len(files) - sum(len(m) for k, m in groups.items() if k[0] == 'album' and len(m) > 1)

    print()
    print("=== plan ===")
    print(f"  album groups (>=2 tracks) : {album_groups}")
    print(f"  tracks becoming albums    : {sum(len(m) for k, m in groups.items() if k[0]=='album' and len(m)>1)}")
    print(f"  true singletons           : {singleton_count}")
    print(f"  files moving to albums/   : {len(album_moves)}")
    print(f"  files moving to singles/  : {len(singleton_moves)}")
    print(f"  files already in place     : {noop}")
    print(f"  albumartist tags to write : {0 if no_tag_write else len(tag_writes)}")
    print(f"  'Various Artists' albums  : {len(va_groups)}")
    print(f"  split (false VA collision): {len(split_groups)}")

    if va_groups:
        print("\n  VA albums (no single majority artist -> filed under 'Various Artists'):")
        for album, n, srcs in sorted(va_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}  (from {len(srcs)} folder{'s' if len(srcs)!=1 else ''})")

    if split_groups:
        print("\n  split apart (Bug 2 - same-titled but unrelated singles, filed separately"
              " instead of merged as 'Various Artists'):")
        for album, n in sorted(split_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}")

    # suspiciously large groups are a wrong-merge smell - list the biggest
    big = sorted(((dominant_album(m), len(m), os.path.basename(os.path.dirname(m[0]['path'])))
                  for k, m in groups.items() if k[0] == 'album' and len(m) > 1),
                 key=lambda x: -x[1])[:15]
    if big:
        print("\n  largest album groups (review for wrong merges - same album name, different real albums):")
        for album, n, cur in big:
            print(f"    {n:>5} files  {album!r}  (now in: {cur})")

    if verbose:
        if album_moves:
            print("\n  album moves:")
            for src, dst, aa in album_moves[:5000]:
                print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")
        if singleton_moves:
            print("\n  singleton moves:")
            for src, dst in singleton_moves[:5000]:
                print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")

    if not apply:
        print("\ndry run - re-run with --apply to move files and write tags.")
        if tag_writes:
            print(f"(would write albumartist tags on {len(tag_writes)} files; pass --no-tag-write to skip)")
        return True

    if album_moves:
        print(f"\nmoving {len(album_moves)} files into albums/...")
        for src, dst, aa in album_moves:
            safe_move(src, dst)
    if singleton_moves:
        print(f"moving {len(singleton_moves)} files into singles/...")
        for src, dst in singleton_moves:
            safe_move(src, dst)
    prune_empty_dirs(crate)

    if not no_tag_write and tag_writes:
        print(f"writing albumartist tags on {len(tag_writes)} files...")
        # after the move, re-resolve each path: file may have moved to its album folder
        moved = {os.path.normpath(s): d for s, d, _ in album_moves}
        for src, aa in tag_writes:
            path = moved.get(os.path.normpath(src), src)
            write_tag(path, albumartist=aa)
    elif no_tag_write:
        print("(--no-tag-write: albumartist tags left as-is - albums may re-split on a future beets run)")

    print("\ndone.")
    print("note: beets.db now points at old file paths - it's stale until rebuilt.")
    print("      rebuild with:  uv run organize cleanup --rebuild-db")
    print("      (or re-run --apply --rebuild-db next time)")

    if rebuild_db_flag:
        rebuild_db(crate, config_path())

    return True