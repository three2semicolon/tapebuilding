"""organize.cleanup.apply - run_cleanup(): the regular regroup-in-place
pass. calls grouping.py's group_files()/build_plan() to decide the
plan, then performs the moves + albumartist tag-writes and prints the
dry-run/applied report. cli.py's `organize cleanup` (no --resplit)
entry point.
"""

import os
import sys

from lib.tags import (
    canonical_albumartist,
    dominant_album,
    read_tags,
    safe_move,
    scan_audio,
    write_tag,
)
from lib.text import normalize_key, split_artists

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


# Known label albumartists that are legitimate for compilations/remix albums
# These are labels that release albums under their own name (e.g. "Monstercat 030")
KNOWN_LABEL_ALBUMARTISTS = {
    'monstercat', 'zephyr', 'daruma', 'joekay', 'joekays',
    'soulection', 'mrsuit', 'chillhop', 'chillhopmusic', 'lofigirl',
    'strangefruits', 'bitbird', 'foreignfamilycollective', 'owsel',
    'gravitas', 'gravitasrecordings', 'wakaan', 'deadbeats', 'neversaydie',
    'disciple', 'disciplerecordings', 'rampage', 'subsidia', 'ophelia',
    'annihilation', 'bassrush', 'insomniac', 'ukf', 'ukfmusic',
    'proximity', 'proximitymusic', 'mrsuicidesheep', 'suicidesheep',
    'tasty', 'tastynetwork', 'ninety9lives', 'nocopyrightsounds', 'ncs',
    'monstercatinstinct', 'monstercatuncaged', 'monstercatsilk', 'kendricklamar',
    'joekay', 'wuxirecordings'
}



def _is_known_label(aa: str) -> bool:
    """Check if albumartist is a known label (case-insensitive, normalized)."""
    return normalize_key(aa) in KNOWN_LABEL_ALBUMARTISTS


def _is_collaboration(artist: str, albumartist: str) -> bool:
    """True if albumartist appears to be one of the collaborating artists.
    e.g. artist='Skrillex & Fred again..', albumartist='Skrillex' -> True
    Uses normalized token overlap."""
    artist_tokens = {normalize_key(a) for a in split_artists(artist or '')}
    aa_norm = normalize_key(albumartist or '')
    return aa_norm in artist_tokens


def check_tags(crate=None, apply=False, verbose=False):
    """scan singles/ and albums/ for albumartist tag anomalies and report
    (with --apply: fix) them. targets two corruption patterns:

      singles/: a file in singles/ carries a non-empty albumartist that is
        neither explicit VA nor its own artist nor a known label nor a
        collaboration partner - the fingerprint of a past wrong merge
        (canonical_albumartist() picked the other artist on a 2-track tie
        and cleanup --apply wrote it; the file went to singles/ but the tag
        stuck). e.g. Diversa - Ego Death.mp3 in singles/ with
        albumartist='The Internet' from a wrong merge with the Internet's
        same-titled album. with --apply, set albumartist to the track's
        own artist (not clear - we always want an albumartist).

      albums/: a file whose albumartist disagrees with the folder's
        canonical albumartist (computed over the folder's members) - a
        straggler tagged by a different album name/artist. with --apply,
        write the canonical value.

    dry-run by default (reports only); plain, import-safe entry point."""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    crate = resolve_crate(crate)
    print(f"crate : {crate}")
    print(f"mode  : {'apply (tags written)' if apply else 'dry run (nothing changes)'}")
    print()

    suspicious = []   # (path, kind, current, expected, reason)
    for sub in ('singles', 'albums'):
        root = os.path.join(crate, sub)
        if not os.path.isdir(root):
            continue
        for dp, dirs, fns in os.walk(root):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            # per-album-folder canonical, computed over that folder's own files
            folder_files = []
            for fn in sorted(fns):
                if fn.lower().endswith(('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac')):
                    tags = read_tags(os.path.join(dp, fn))
                    if tags:
                        folder_files.append(tags)
            if sub == 'singles':
                for t in folder_files:
                    aa = t['albumartist'] or ''
                    artist = t['artist'] or ''
                    if not aa:
                        # no albumartist at all -> should be set to artist
                        suspicious.append((t['path'], 'singles', '(empty)', artist, 'missing'))
                        continue
                    aa_norm = normalize_key(aa)
                    if aa_norm in ('variousartists', 'va'):
                        continue  # explicit compilation tag - leave alone
                    if aa_norm == normalize_key(artist):
                        continue  # matches its own artist - fine for a single
                    if _is_known_label(aa):
                        continue  # known label albumartist - legitimate
                    if _is_collaboration(artist, aa):
                        continue  # albumartist is one of the collaborating artists - legitimate
                    # True corruption: disjoint albumartist (e.g. Spencer with albumartist=Anysia Kym)
                    # Fix: set to the track's own artist
                    suspicious.append((t['path'], 'singles', aa, artist, 'corruption'))
            else:  # albums
                if not folder_files:
                    continue
                canonical = canonical_albumartist(folder_files)
                for t in folder_files:
                    aa = t['albumartist'] or ''
                    if normalize_key(aa) != normalize_key(canonical):
                        suspicious.append((t['path'], 'albums', aa, canonical, 'mismatch'))

    print(f"files with anomalous albumartist : {len(suspicious)}")
    for path, kind, cur, exp, reason in suspicious:
        rel = os.path.relpath(path, crate)
        if kind == 'singles':
            if reason == 'missing':
                action = 'set to artist' if apply else 'would set to artist'
            else:  # corruption
                action = f'set to {exp!r}' if apply else f'would set to {exp!r}'
            print(f"  singles/  {rel!r}")
            print(f"    albumartist={cur!r} -> {action} ({reason})")
        else:
            action = 'fix' if apply else 'would fix'
            print(f"  albums/   {rel!r}")
            print(f"    albumartist={cur!r} != canonical {exp!r} -> {action}")

    if not suspicious:
        print("\nno anomalous albumartist tags found.")
        return {'suspicious': 0, 'fixed': 0}

    if not apply:
        print(f"\ndry run - {len(suspicious)} file(s) would be changed. re-run with --apply to write tags.")
        return {'suspicious': len(suspicious), 'fixed': 0}

    fixed = 0
    for path, kind, cur, exp, reason in suspicious:
        write_tag(path, albumartist=exp)
        fixed += 1
    print(f"\nwrote {fixed} albumartist tag(s).")
    print("note: beets.db may still hold the old tags - rebuild with `uv run organize cleanup --rebuild-db`")
    print("      if you want the library csv/beets.db to match.")
    return {'suspicious': len(suspicious), 'fixed': fixed}


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
    album_moves, singleton_moves, noop, tag_writes, album_tag_writes, va_groups, split_groups = build_plan(groups, crate)

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
    print(f"  album tags to write       : {0 if no_tag_write else len(album_tag_writes)}")
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
        if album_tag_writes:
            print(f"(would write album tags on {len(album_tag_writes)} files; pass --no-tag-write to skip)")
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

    if not no_tag_write and album_tag_writes:
        print(f"writing album tags on {len(album_tag_writes)} files...")
        for src, album in album_tag_writes:
            path = moved.get(os.path.normpath(src), src)
            write_tag(path, album=album)

    print("\ndone.")
    print("note: beets.db now points at old file paths - it's stale until rebuilt.")
    print("      rebuild with:  uv run organize cleanup --rebuild-db")
    print("      (or re-run --apply --rebuild-db next time)")

    if rebuild_db_flag:
        rebuild_db(crate, config_path())

    return True