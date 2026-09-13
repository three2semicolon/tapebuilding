"""organize.cleanup - reorganize the beets crate into proper albums and singles.

repairs the two things the beets two-pass importer gets wrong on this library:
  1. albums split into multiple folders, one per track-artist, because beets
     keyed the album folder on $artist (per-track) instead of $albumartist
     and the source files had no albumartist tag (beets fell back to the
     track artist, which varies on collab/featured tracks).
  2. whole albums scattered as singletons in singles/, because pass 2
     imports every track standalone (no album grouping).

the regrouper works straight off file tags (mediafile), independent of beets:
  - group every audio file in <crate>/albums and <crate>/singles by its album tag
  - >=2 files share an album  -> one album folder, named <albumartist> - <album>
  - exactly 1 file per album   -> singleton in singles/<artist> - <title>
  - no album tag               -> singleton (a file with no album isn't an album)
  - canonical albumartist per group = the dominant artist string across the
    group's files (collab variants "A & B"/"A & C" collapse to "A" when A is
    the majority); fall back to the dominant primary collaborator; else
    "Various Artists" (a true VA compilation like "'SLOWED' EDITS VOL. I").
  - writes the canonical albumartist tag into every album-group file so a
    future beets as-is re-import won't re-split them.
  - skips non-audio files (beets.db, *.log, library.csv, cover art, .nomedia).

idempotent: re-running on an already-clean crate is a no-op.

this file is now just the regroup-in-place *policy* (grouping, planning,
applying the plan, rebuilding beets.db) - the toolkit half (tag reading,
sanitizing, canonical-albumartist/dominant-album picking, the audio-file
walk, safe_move) moved to lib.tags/lib.text during the lib/ refactor, since
lib.catalog.indexer needed the exact same primitives. organize.preimport
imports those from lib now too, instead of via this file.

cli.py owns argument parsing / exit codes; run_cleanup() below is the plain,
import-safe entry point cli.py (and anything else) calls into.

usage (via organize's cli):
  uv run organize cleanup                        # dry-run: print plan, move nothing
  uv run organize cleanup --apply                # move files + write albumartist tags
  uv run organize cleanup --apply --rebuild-db   # ...then rebuild beets.db from the reorganized crate
  uv run organize cleanup --verbose              # print every planned move
  uv run organize cleanup --crate /path/to/crate
"""

import collections
import os
import sys

from lib.paths import resolve as resolve_path
from lib.tags import (
    canonical_albumartist,
    dominant_album,
    safe_move,
    sanitize,
    scan_audio,
    write_tag,
)
from lib.text import normalize_key


def resolve_crate(cli_value=None):
    """crate root from --crate, else ARCHIVE_PATH - required, no expanduser
    fallback. deliberately stricter than lib.paths.archive_path()'s default
    (~/music/tapebuilding): this command moves files and rewrites tags, so
    silently landing on a guessed path instead of erroring is the wrong
    failure mode here. same reasoning applies to organize.beets_import's
    crate resolution."""
    return resolve_path('ARCHIVE_PATH', cli_value, required=True)


def group_files(files):
    """group by normalised album (empty album -> its own single-element bucket so
    it stays a singleton). returns {group_key: [file, ...]} preserving order."""
    groups = collections.OrderedDict()
    for i, f in enumerate(files):
        if f['album']:
            key = ('album', normalize_key(f['album']))
        else:
            key = ('single', i)  # unique per file - never merge missing-album files
        groups.setdefault(key, []).append(f)
    return groups


def build_plan(groups, crate):
    """decide a target path + tag fix for every file.
    returns (album_moves, singleton_moves, noop_count, tag_writes, va_groups)."""
    albums_dir = os.path.join(crate, 'albums')
    singles_dir = os.path.join(crate, 'singles')

    album_moves = []      # (src, dst, new_albumartist)
    singleton_moves = []  # (src, dst)
    tag_writes = []       # (src, new_albumartist)
    va_groups = []        # (album, track_count, src_skewed_folders)
    noop = 0

    # de-dup track numbers within a group: prefer the tag's track, else sequence
    def track_label(idx_in_group, f):
        n = f['track'] or (idx_in_group + 1)
        return f"{int(n) if n else idx_in_group+1:02d}"

    for (kind, _), members in groups.items():
        if kind == 'single' or len(members) == 1:
            # singleton: <crate>/singles/<artist> - <title>.ext
            f = members[0]
            ext = os.path.splitext(f['path'])[1]
            dst = os.path.join(singles_dir,
                               f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}")
            if os.path.normpath(dst) != os.path.normpath(f['path']):
                singleton_moves.append((f['path'], dst))
            else:
                noop += 1
            continue

        # album group
        aa = canonical_albumartist(members)
        album = dominant_album(members)
        folder = sanitize(f"{aa} - {album}") or 'Unknown Album'

        # did we end up at "Various Artists"? flag for the summary
        src_folders = {os.path.basename(os.path.dirname(m['path'])) for m in members}
        if aa == 'Various Artists':
            va_groups.append((album or folder, len(members), sorted(src_folders)))

        # tag writes: enforce the canonical albumartist so future beets runs don't split
        for m in members:
            if normalize_key(m['albumartist'] or '') != normalize_key(aa):
                tag_writes.append((m['path'], aa))

        seen_names = set()
        for idx, m in enumerate(members):
            ext = os.path.splitext(m['path'])[1]
            name = f"{track_label(idx, m)} - {sanitize(m['artist'])} - {sanitize(m['title'])}{ext}"
            # rare filename collision inside the album -> disambiguate
            base, sfx = os.path.splitext(name); c = 2
            while name.lower() in seen_names:
                name = f"{base} ({c}){sfx}"; c += 1
            seen_names.add(name.lower())
            dst = os.path.join(albums_dir, folder, name)
            if os.path.normpath(dst) != os.path.normpath(m['path']):
                album_moves.append((m['path'], dst, aa))
            else:
                noop += 1

    return album_moves, singleton_moves, noop, tag_writes, va_groups


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
    """config.yaml sits alongside this file in organize/."""
    return os.path.join(os.path.dirname(__file__), 'config.yaml')


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
    album_moves, singleton_moves, noop, tag_writes, va_groups = build_plan(groups, crate)

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

    if va_groups:
        print("\n  VA albums (no single majority artist -> filed under 'Various Artists'):")
        for album, n, srcs in sorted(va_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}  (from {len(srcs)} folder{'s' if len(srcs)!=1 else ''})")

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